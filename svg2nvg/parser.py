# Copyright (c) 2014 Olli Wang. All right reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
import re
import sys
import xml.etree.ElementTree as ET

from svg2nvg import definitions
from svg2nvg import generator


# A list of tag names that should be ignored when parsing.
ignored_tags = ('comment', 'desc', 'title', 'namedview')
# A list of supported path commands and the number of parameters each command
# requires.
path_commands = (('A', 7), ('C', 6), ('H', 1), ('L', 2), ('M', 2), ('Q', 4),
                 ('S', 4), ('T', 2), ('V', 1), ('Z', 0))


def attribute(method):
    """Decorator for parsing element attributes.

    Methods with this decorator must return a dictionary with interested
    attributes. The dictionary will then be passed to corresponded generator
    method as parameters.
    """
    def inner(*args, **kwargs):
        self = args[0]
        result = method(*args, **kwargs)
        if result:
            func = getattr(self.generator, method.__name__.rsplit('_')[-1])
            func(**result)
        return result
    return inner

def extract_number_from_string(str):
    result = re.search(r'\d+', str)
    return result[0] if result else 0

def element(method):
    """Decorator for parsing a element.

    This decorator simply wraps the method between generator's begin_element()
    and end_element() calls with the tag name as the parameter.
    """
    def inner(*args, **kwargs):
        self = args[0]
        element = args[1]
        self.begin_element(element)
        method(*args, **kwargs)
        self.end_element(element)
    return inner

def get_element_tag(element):
    """Returns the tag name string without namespace of the passed element."""
    return element.tag.rsplit('}')[1]


class SVGParser(object):

    def __init__(self, context='context'):
        self.context = context
        self.stmts = list()
        self.styles = list()

    @attribute
    def __parse_bounds(self, element):
        args = dict()
        args['x'] = element.attrib.get('x', 0)
        args['y'] = element.attrib.get('y', 0)
        args['width'] = element.attrib.get('width', 0)
        args['height'] = element.attrib.get('height', 0)
        return args

    @element
    def __parse_circle(self, element):
        self.generator.circle(**element.attrib)
        self.__parse_fill(element)
        self.__parse_stroke(element)

    def __parse_element(self, element):
        tag = get_element_tag(element)
        print("TAG: %s" % tag)
        if tag in ignored_tags:
            return

        # Determines the method for parsing the passed element.
        method_name = '_' + self.__class__.__name__ + '__parse_%s' % tag.lower()
        try:
            method = getattr(self, method_name)
        except AttributeError:
            print('Error: %r element is not supported' % tag)
            exit(1)
        else:
            method(element)

    @element
    def __parse_ellipse(self, element):
        self.generator.ellipse(**element.attrib)
        self.__parse_fill(element)
        self.__parse_stroke(element)

    @attribute
    def __parse_fill(self, element):
        args = dict()
        if 'fill' in element.attrib:
            fill = element.attrib['fill']
        else:
            fill = self.__parse_style(element, 'fill')

        print("FILL:", fill)
        if fill == 'none' or fill == 'transparent':
            return args

        # Expands three-digit shorthand of hex color.
        if fill.startswith("#") and len(fill) == 4:
            fill = '#%c%c%c%c%c%c' % (fill[1], fill[1], fill[2], fill[2],
                                      fill[3], fill[3])

        args['fill'] = fill
        args['fill-opacity'] = float(element.attrib.get('opacity', 1)) * \
                               float(element.attrib.get('fill-opacity', 1))
        return args

    @element
    def __parse_g(self, element):
        # Gathers all group attributes at current level.
        self.group_attrib.append(element.attrib)
        group_attrib = dict()
        for attrib in self.group_attrib:
            group_attrib.update(attrib)

        # Applies group attributes to child elements.
        for child in element:
            child.attrib.update(group_attrib)
            self.__parse_element(child)

        # Removes the group attributes at current level.
        self.group_attrib.pop()

    @element
    def __parse_line(self, element):
        self.generator.line(element.attrib['x1'], element.attrib['y1'],
                            element.attrib['x2'], element.attrib['y2'])
        self.__parse_fill(element)
        self.__parse_stroke(element)

    @element
    def __parse_lineargradient(self, element):
        self.generator.definitions[element.get('id')] = \
            definitions.LinearGradientDefinition(element)

    @element
    def __parse_path(self, element):
        def execute_command(command, parameters):
            if not command:
                return
            for path_command in path_commands:
                if path_command[0] == command.upper():
                    break
            else:
                print("Path command %r is not supported." % command)
            parameter_count = path_command[1]

            if parameter_count == 0:
                if parameters:
                    print("Path command %r should not take parameters: %s" % \
                          (command, parameters))
                    exit(1)
                self.generator.path_command(command)
            else:
                # Checks if the number of parameters matched.
                if (len(parameters) % parameter_count) != 0:
                    print("Path command %r should take %d parameters instead "
                          "of %d" % (command, parameter_count, len(parameters)))
                    exit(1)
                while parameters:
                    self.generator.path_command(command,
                                                *parameters[:parameter_count])
                    parameters = parameters[parameter_count:]

        parameters = list()
        command = None
        found_decimal_separator = False
        parameter_string = list()

        commands = tuple(c[0] for c in path_commands) + \
                   tuple(c[0].lower() for c in path_commands)

        self.generator.begin_path_commands()
        for char in element.attrib['d']:
            if char in ['\n', '\t']:
                continue
            elif char in commands:  # found command
                if parameter_string:
                    parameters.append(''.join(parameter_string))
                    parameter_string = list()
                execute_command(command, parameters)
                command = char
                parameters = list()
                found_decimal_separator = False
            elif char in [' ', ',', '-']:
                if parameter_string:
                    parameters.append(''.join(parameter_string))
                    parameter_string = list()
                    found_decimal_separator = False
                if char in ['-']:
                    parameter_string.append(char)
                    found_decimal_separator = False
            elif char == '.':
                if found_decimal_separator:
                    parameters.append(''.join(parameter_string))
                    parameter_string = list()
                    parameter_string.append(char)
                else:
                    found_decimal_separator = True
                    parameter_string.append(char)
            elif command is not None:
                parameter_string.append(char)

        if parameter_string:
            parameters.append(''.join(parameter_string))
            parameter_string = list()
        execute_command(command, parameters)
        self.generator.end_path_commands()

        self.__parse_fill(element)
        self.__parse_stroke(element)

    @element
    def __parse_polygon(self, element):
        self.generator.polygon(**element.attrib)
        self.__parse_fill(element)
        self.__parse_stroke(element)

    @element
    def __parse_polyline(self, element):
        self.generator.polyline(**element.attrib)
        self.__parse_fill(element)
        self.__parse_stroke(element)

    @element
    def __parse_rect(self, element):
        self.__parse_transform(element)
        args = self.__parse_bounds(element)
        self.generator.rect(**args)
        self.__parse_fill(element)
        self.__parse_stroke(element)

    @attribute
    def __parse_stroke(self, element):
        args = dict()
        if 'stroke' in element.attrib:
            stroke = element.attrib['stroke']
        else:
            stroke = self.__parse_style(element, 'stroke')

        # if stroke == 'none' or stroke == 'transparent':
        #     return dict()
        # if stroke != 'none' and stroke != 'transparent':
        args['stroke'] = stroke
        args['stroke-opacity'] = float(element.attrib.get('opacity', 1)) * \
                                 float(element.attrib.get('stroke-opacity', 1))

        for attrib in ['linecap', 'linejoin', 'miterlimit', 'width']:
            attrib = 'stroke-%s' % attrib
            if attrib in element.attrib:
                args[attrib] = element.attrib[attrib]
            else:
                value = self.__parse_style(element, attrib)
                if value != 'none':
                    args[attrib] = value

        if 'stroke-width' in args:
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", args['stroke-width'])
            if numbers:
                args['stroke-width'] = numbers[0]

        if 'stroke-width' in args and float(args['stroke-width']) < 1:
            return dict()

        print("Stroke:", args)
        return args

    def __parse_style(self, element, name):
        if 'style' in element.attrib:
            style = element.attrib['style']
            print("--- STYLE: ", style)
            match = re.search(r'%s:(.*?);' % name, style)
            if match:
                return match.group(1)
        return 'none'

    @attribute
    def __parse_transform(self, element):
        if 'transform' not in element.attrib:
            return dict()
        return {'transform': element.attrib['transform']}

    def __parse_tree(self, tree):
        root = tree.getroot()
        root_tag = get_element_tag(root)
        if root_tag != 'svg':
            print("Error: the root tag must be svg instead of %r" % root_tag)
            exit(1)

        del self.stmts[:]  # clears the cached statements.

        try:
            self.canvas_width = root.attrib['width']
            self.canvas_height = root.attrib['height']
        except KeyError:
            view_box = root.attrib['viewBox'].split(' ')
            self.canvas_width = view_box[2]
            self.canvas_height = view_box[3]
        self.generator = generator.Generator(self.stmts, self.context)
        self.group_attrib = list()

        self.begin_element(root)
        for child in root:
            self.__parse_element(child)
        self.end_element(root)

    def begin_element(self, element):
        tag = get_element_tag(element)
        print("BEGIN <%s>\n" % tag)
        self.generator.begin_element(tag)

    def end_element(self, element):
        tag = get_element_tag(element)
        print("END <%s>\n" % tag)
        self.generator.end_element(tag)

    def get_content(self):
        return '\n'.join(self.stmts)

    def get_header_file_content(self, filename, nanovg_include_path,
                                uses_namespace=False, builds_object=False,
                                prototype_only=False):
        basename = os.path.splitext(os.path.basename(filename))[0]
        guard_constant = 'SVG2NVG_%s_H_' % basename.upper()
        title = basename.title().replace('_', '')

        result = '#ifndef %s\n' % guard_constant
        result += '#define %s\n\n' % guard_constant

        if nanovg_include_path:
            result += '#include "%s"\n\n' % nanovg_include_path

        if uses_namespace:
            result += 'namespace svg2nvg {\n\n'

        if builds_object:
            function_name = 'Draw'
#             result += '''#ifndef SVG2NVG_DRAWING_H_
# #define SVG2NVG_DRAWING_H_

# class Drawing {};

# #endif  // SVG2NVG_DRAWING_H_

# '''

            result += 'class %s : public Drawing {\n' % title
            result += ' public:\n'
            # result += '  static constexpr double kWidth = %s;\n' % \
            result += '  double GetWidth() const final { return %s; }\n' % \
                         extract_number_from_string(self.canvas_width)
            result += '  double GetHeight() const final { return %s; }\n\n' % \
                         extract_number_from_string(self.canvas_height)
            # result += '  static constexpr double  kHeight = %s;\n\n' % \
            # result += '  static '
        else:
            function_name = 'Render%s' % title

        prototype = '  void %s(NVGcontext *%s) const final' % \
                    (function_name, self.context)
        if prototype_only:
            result += '%s;\n' % prototype
        else:
            result += 'static %s {\n' % prototype
            for stmt in self.stmts:
                result += '  %s\n' % stmt
            result += '}\n'

        if builds_object:
            result += '};\n'

        result += '\n'
        if uses_namespace:
            result += '}  // namespace svg2nvg\n\n'
        result += '#endif  // %s\n' % guard_constant
        return result

    def get_source_file_content(self, filename, nanovg_include_path,
                                uses_namespace=False,
                                header_include_path=None,
                                builds_object=False):
        result = ''
        basename = os.path.splitext(os.path.basename(filename))[0]
        if header_include_path is None:
            header_include_path = ''
        header_name = '%s.h' % basename
        header_include_path = os.path.join(header_include_path, header_name)
        result += '#include "%s"\n\n' % header_include_path

        if nanovg_include_path:
            result += '#include "%s"\n\n' % nanovg_include_path

        if uses_namespace:
            result += 'namespace svg2nvg {\n\n'

        title = basename.title().replace('_', '')
        result += 'void '
        if builds_object:
            function_name = 'Draw'
            result += '%s::' % title
        else:
            function_name = 'Render%s' % title
        result += '%s(NVGcontext *%s) const {\n' % (function_name, self.context)
        for stmt in self.stmts:
            result += '  %s\n' % stmt
        result += '}\n\n'
        if uses_namespace:
            result += '}  // namespace svg2nvg\n'
        return result

    def parse_file(self, filename):
        try:
            tree = ET.parse(filename)
        except IOError:
            print('Error: cannot open SVG file at path: %s' % filename)
            exit(1)
        else:
            self.__parse_tree(tree)

    def parse_string(self, string):
        tree = ET.fromstring(string)
        self.__parse_tree(tree)
