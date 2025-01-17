// Copyright 2017-2021 The Verible Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "common/util/user_interaction.h"

#include <iostream>
#include <string>

#include "absl/strings/str_cat.h"
#include "absl/strings/string_view.h"

#ifndef _WIN32
#include <unistd.h>  // for isatty
#else
#include <io.h>
// MSVC recommends to use _isatty...
#define isatty _isatty
#endif

namespace verible {

bool IsInteractiveTerminalSession() {
  return isatty(0);  // Unix: STDIN_FILENO; windows: _fileno( stdin )
}

char ReadCharFromUser(std::istream& input, std::ostream& output,
                      bool input_is_terminal, absl::string_view prompt) {
  if (input_is_terminal) {
    // Terminal input: print prompt, read whole line and return first character.
    output << prompt << std::flush;

    std::string line;
    std::getline(input, line);

    if (input.eof() || input.fail()) {
      return '\0';
    }
    return line.empty() ? '\n' : line.front();
  }
  // Input from a file or pipe: no prompt, read single character.
  char c;
  input.get(c);
  if (input.eof() || input.fail()) {
    return '\0';
  }
  return c;
}

namespace term {
// TODO(hzeller): assumption here that basic ANSI codes work on all
// platforms, but if not, change this with ifdef.
static constexpr absl::string_view kBoldEscape("\033[1m");
static constexpr absl::string_view kInverseEscape("\033[7m");
static constexpr absl::string_view kNormalEscape("\033[0m");

std::string bold(absl::string_view s) {
  if (!IsInteractiveTerminalSession()) return std::string(s);
  return absl::StrCat(kBoldEscape, s, kNormalEscape);
}
std::string inverse(absl::string_view s) {
  if (!IsInteractiveTerminalSession()) return std::string(s);
  return absl::StrCat(kInverseEscape, s, kNormalEscape);
}
}  // namespace term
}  // namespace verible
