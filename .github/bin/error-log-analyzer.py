#!/usr/bin/python3

# Copyright 2023 The Verible Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

###
# Analysis tool for the generated error logs from smoke-test-error-logger.sh
# Arguments that need to be supplied:
#   - path: path to the directory where all the *-nonzeros directories are
# This script checks various conditions that classify each error based on
# criteria and previous errors, such that a clear picture is generated
# in the end of what is the main cause of non-zero exits in the smoke tests.
#
# Error categories:
# - Undefined: Errors that not fit any criteria
# - Slang: Errors that also are present in slang, verifying legitimacy of them
# - Related to slang: Errors that occured after a slang error; if there was a
#                     syntax error, a lot of later tokens will not fit
#                     causing additional errors.
# - Define: Errors that occured because of a macro call in a module
#           parameter list. Those usually also contain the line delimiters
#           of which the parser will be unaware causing syntax errors.
# - Define caused: Syntax errors that occur after a missing define.
#                  Analogous to related to slang, those are syntax errors
#                  caused by earlier "missing" tokens.
# - Unresolved macro: Errors that occured because of an unresolved macro call
# - Test designed to fail: Errors that are intentional, present in ivtest
# - Misc preprocessor: Errors that are not related to the above categories
#                      but are related to the preprocessor
# - Related to misc preprocessor: Errors that are related to the above
# - Standalone header: Errors that occured while parsing a header file, that
#                      really should not be parsed outside of its context where
#                      it is included
###

import glob
import tempfile
import subprocess
import re
from collections import defaultdict
from copy import deepcopy
import argparse
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("path")
args = parser.parse_args()
root = args.path


# structure that contains the information about a particular error
class ErrorContainer:
    def __init__(
            self,
            project,
            source_path,
            line_number,
            start_char,
            end_char,
            error_text,
            category='undefined'
    ):
        self.project = project
        self.source_path = source_path
        self.line_number = line_number
        self.start_char = start_char
        self.end_char = end_char
        self.category = category
        self.error = error_text
        self.slang_output = None

    def __str__(self):
        return f"Error in project: {self.project}\
 of category: {self.category}\n \
 source file: {self.source_path}\n \
 on line: {self.line_number}, col: {self.start_char}-{self.end_char}\n \
 full text:{self.error}"


# root path where the nonzero data is unpacked/created
error_dirs = glob.glob(root+'/*-nonzeros')
project_urls = sorted([
            "https://github.com/lowRISC/ibex",
            "https://github.com/lowRISC/opentitan",
            "https://github.com/chipsalliance/Cores-VeeR-EH2",
            "https://github.com/openhwgroup/cva6",
            "https://github.com/SymbiFlow/uvm",
            "https://github.com/taichi-ishitani/tnoc",
            "https://github.com/jamieiles/80x86",
            "https://github.com/SymbiFlow/XilinxUnisimLibrary",
            "https://github.com/black-parrot/black-parrot",
            "https://github.com/steveicarus/ivtest",
            "https://github.com/krevanth/ZAP",
            "https://github.com/trivialmips/nontrivial-mips",
            "https://github.com/pulp-platform/axi",
            "https://github.com/rsd-devel/rsd",
            "https://github.com/syntacore/scr1",
            "https://github.com/bespoke-silicon-group/basejump_stl"
])

urls_with_names = sorted(
        [(i, i.split('/')[-1]) for i in project_urls],
        key=lambda x: x[1].lower()
)


# method that classifies the errors depending on some categories
# and the internal state of the error checker - for each file the
# state is reset, as leaving it present in between files was not
# needed at the current moment
def error_classifier(src, line, state, project):
    # extracting the postition presetned as
    # filename:line:starting_col:ending_col:
    error_pos = re.search(
            r":[0-9]+:[0-9]+(-[0-9]+)*:",
            line
    )
    line_number = error_pos[0].split(':')[1]
    start_char = error_pos[0].split(':')[2]
    end_char = start_char.split('-')[-1]
    start_char = start_char.split('-')[0]

    # creating the container for the error
    err = ErrorContainer(
            project_name,
            source_path,
            int(line_number),
            int(start_char),
            int(end_char),
            line
    )
    # error processing

    # check if the macro had not been resolved and if so - mark the error
    if re.search(
            r'Error expanding macro identifier',
            line):
        err.category = 'unresolved-macro'
    # find a syntax error where the define is placed near
    # (inside of the parameter declaration) of a module -
    # it causes a chain of syntax errors later so change
    # the state to another value
    if state == 2:
        err.category = 'related-to-slang-validated-error'
    if err.source_path[-4:] == '.svh' and re.search(
            r'syntax error at token "(?:(?!include|define|undef|ifdef|ifndef).)+',  # noqa: E501
            line):
        err.category = 'standalone-header'
    elif re.search(
            r'syntax error at token "`(?:(?!include|define|undef|ifdef|ifndef).)+',  # noqa: E501
            line):
        if re.search(
                "module",
                '\n'.join(src[max(err.line_number-30, 0):err.line_number])):
            state = 1
            err.category = 'define-in-module'
        else:
            state = 3
            err.category = 'misc-preprocessor'
    elif state == 3 and re.search(
            "syntax error at token",
            line):
        err.category = 'misc-preprocessor-related'
    # if the state is 1 (define-in-module error), then every subsequent syntax
    # error should be marked as related to it
    elif state == 1 and re.search(
            "syntax error at token",
            line):
        err.category = 'caused-by-define-in-module'
    # usually the syntax error related to the define-in-module problem end at
    # an endmodule token - change the state back to default when it is detected
    if state == 1 and re.search(
            "syntax error at token \"endmodule\"",
            line):
        state = 0
    # see if in ivtest - a project with some files having intentional
    # errors for testing purposes - the presence of an error is indicated
    # in the file name
    if 'ivtest' in project and re.search(
            r'ivtest\/(\w+\/)+.*(fail|error)\w*\.\w+',
            line):
        err.category = 'ivtest-designed-to-fail'
    return err, state


def get_slang_output(srcpath):
    # subprocess run where the output is captured into a string
    proc = subprocess.run(
            ["slang", '--error-limit=0', srcpath.strip()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
    )
    # split the output into lines
    slang_output = proc.stderr.decode('utf-8').split('\n')
    return slang_output


# function that given an array of strings joins them until
# a regex matches:
def join_until_regex(src, regex):
    new_src = []
    joined = ''
    for line in src:
        if not re.search(regex, line):
            joined += line
        elif joined != '':
            new_src.append(joined)
            joined = line
        else:
            joined = line
    return new_src


# a function that returns true if there is no match with common
# preprocessor / include problems that are just not important for this
def is_slang_line_important(line):
    return re.search(
            r'error:( \w*)*(unknown|undeclared)',
            line) is None


def validate_slang(src, line, state, project, srcpath, err):
    if err.slang_output is None:
        err.slang_output = get_slang_output(srcpath)
    # split the output such that there is one error per string in the
    # errors list
    errors = join_until_regex(err.slang_output, re.escape(srcpath))
    # extract the error line number and column from the
    # slang errors
    for line in errors:
        error_pos = re.search(
                r":[0-9]+:[0-9]+:",
                line
        )
        line_number = int(error_pos[0].split(':')[1].strip())
        start_char = int(error_pos[0].split(':')[2].strip())
        # just to make sure that those were extracted such that
        # they are comparable
        assert isinstance(line_number, type(err.line_number))

        # check if the slang error is in the vicinity of the
        # original error and if the error is not a complaint
        # about a missing macro,function, etc
        if line_number == err.line_number and \
                abs(start_char - err.start_char) <= 3 and \
                is_slang_line_important(line):
            err.category = 'slang-verified-error'
            state = 2
    return err.category, state


def list_factory():
    return []


# load files and get the metadata from them
for i, (url, project_name) in zip(error_dirs, urls_with_names):
    assert ("-".join(i.split('/')[-1].split('-')[:-1]) == project_name)
    # for tempdirname in ['/tmp/testing-area']:
    with tempfile.TemporaryDirectory() as tempdirname:
        # keeps the indented block for
        # swapping with the `with` statement
        # while having a predictable path
        p = subprocess.run(
                ["git clone " + url+' '+tempdirname+'/'+project_name],
                stdout=subprocess.PIPE, shell=True,
                stderr=subprocess.DEVNULL
        )
        project_files = glob.glob(
                '**',
                root_dir=tempdirname+'/'+project_name,
                recursive=True
        )
        verible_error_files = glob.glob('**', root_dir=i, recursive=True)
        project_errors = defaultdict(list_factory)
        for file in verible_error_files:
            file_with_tool = ':'.join(file.split('-')[1:])
            exit_code = int(file.split('-')[0])
            if exit_code == 1:
                tool = file_with_tool.split('_')[-1].replace(':', '-')
                filename = '_'.join(file_with_tool.split('_')[:-1])

                # if there were dashes ('-') in the file name, they
                # need to be re-replaced back from colons
                if len(filename.split(':')) > 1:
                    filename = filename.replace(':', '-')

                source_path_matches = [
                        i for i in project_files
                        if re.search(re.escape(filename), i)
                ]
                source_path = None
                if len(source_path_matches) > 1:
                    # the path needs to be scooped from the file itself
                    with open(i+'/'+file, 'r') as f:
                        for line in f:
                            m = re.search(
                                    project_name+r"(\/[\w,:\-\.]+)+\/[^:]+",
                                    line
                            )
                            if m and source_path is None:
                                source_path = "/".join(m[0].split('/')[1:])
                                break
                elif 'project' not in tool:
                    try:
                        source_path = source_path_matches[0]
                    except IndexError:
                        print(file, filename)
                        input()
                        break
                else:
                    # TODO: deal with the project problems later
                    continue
                with open(tempdirname+'/'+project_name+'/'+source_path) as s:
                    src = s.readlines()
                    state = 0
                    with open(i+'/'+file, 'r') as f:
                        for line in f:
                            err, state = error_classifier(
                                    src,
                                    line,
                                    state,
                                    project_name
                            )
                            if err.category == 'undefined':
                                srcpath = tempdirname+'/' + \
                                        project_name+'/' + \
                                        source_path
                                err.category, state = validate_slang(
                                        src,
                                        line,
                                        state,
                                        project_name,
                                        srcpath,
                                        err
                                )
                            # if err.category == 'slang-verified-error':
                            #     print(err, "state: ", state)
                            # if 'slang' in err.category:
                            #     print("\n".join(err.slang_output))
                            project_errors[project_name].append(deepcopy(err))
    # Per-project stats
    all = len(project_errors[project_name])
    error_types = defaultdict(int)
    for error in project_errors[project_name]:
        error_types[error.category] += 1
    print(
        "Project: ", project_name,
        "\n  -All:",
        all,
        "\n  -Undefined:",
        error_types['undefined'],
        "\n  -Slang:",
        error_types['slang-verified-error'],
        "\n  -Related to slang:",
        error_types['related-to-slang-validated-error'],
        "\n  -Define in module:",
        error_types['define-in-module'],
        "\n  -Define-in-module caused:",
        error_types['caused-by-define-in-module'],
        "\n  -Unresolved macro:",
        error_types['unresolved-macro'],
        "\n  -Test designed to fail:",
        error_types['ivtest-designed-to-fail'],
        "\n  -Misc. preporcesor: ",
        error_types['misc-preprocessor'],
        '\n  -Related to misc. preprocessor: ',
        error_types['misc-preprocessor-related'],
        '\n  -Standalone header: ',
        error_types['standalone-header']
    )
    # check if the output is sane
    assert sum([error_types[i] for i in error_types.keys()]) == all
    assert error_types['define-in-module'] == 0 or \
        error_types['define-in-module'] > 0
    assert error_types['related-to-slang-validated-error'] == 0 or \
        error_types['slang-verified-error'] > 0
    assert error_types['misc-preprocessor-related'] == 0 or \
        error_types['misc-preprocessor-related'] > 0
    # break
