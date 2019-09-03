Tiny Unified Runner N' Tester (Turnt)
=====================================

Turnt is a simple testing tool inspired by [Cram][] and [LLVM's lit][lit].
The idea is that each test consists a single input file and one or more output files.
You want to run a command on the input file and check that the output is equal to the expected output files.

To use it:

1. Create a test file.
2. Decide what command you need to run on this input.
   There are two options:
   You can put this in a `turnt.toml` config file alongside your test: use `command = "mycmd {filename}"` to pass the test file as an argument to `mycmd`.
   Or you can embed it in a comment in the test file itself: use `CMD: mycmd {filename}`.
3. Get the initial output.
   Run `turnt --save foo.t` to generate the expected output in `foo.out`.
   You'll want to check these output files into version control along with your test.
4. Run the tests.
   Use `turnt foo.t` to check a test output.
   If a test fails, add `--diff` to compare the actual and expected outputs.

[cram]: https://bitheap.org/cram/
[lit]: https://llvm.org/docs/CommandGuide/lit.html


Install
-------

This is a Python 3 tool.
Install it with [pip][]:

    $ pip install --user turnt

Or, if you want to work on Turnt, you can install [Flit][], clone this repository, and type this to get a "live" installation with a symlink:

    $ flit install --symlink --user

[pip]: https://pip.pypa.io/
[flit]: https://flit.readthedocs.io/


Details
-------

These options are available in `turnt.toml`:

- `command`.
  This is a shell command to run for each test input.
- `output`.
  This is a mapping from extensions to output files to collect from each test.
  For example, use `output.txt = "my_output.txt"` to collect `my_output.txt` after each text extension and save it in `<test-name>.txt`.
  Use `-` to indicate the command's standard output.
  The default is like `output.out = "-"`, i.e., capture stdout and save it in `<test-name>.out`.
  You can include this yourself or omit if if you want to ignore the standard output.

Equivalently, you can embed options in test files themselves:

- `CMD: <command>` overrides `command` from the configuration.
- `OUT: <ext> <filename>` overrides `output` from the configuration.
  You can specify multiple files this way: one line per file.
- `ARGS: <arguments>`. Add arguments to a configured command (see below).

In commands and filenames, you can use certain patterns that get substituted with details about the tests:

- `{filename}`: The name of the test file (without the directory part).
- `{base}`: Just the basename of the test file (no extension).
- `{args}`: Extra arguments specified using `ARGS:` in the test file.

If you need multiple files for a test, you can use a directory instead of a file.
Turnt will not attempt to read embedded comment options from directories, and outputs will be placed *inside* the test directory instead of adjacent to it.


TAP
---

Turnt outputs [TAP][] results by default.
To make the output more pleasant to read, you can pipe it into a tool like [tap-difflet][]:

    $ npm install -g tap-difflet
    $ turnt *.t | tap-difflet

[tap]: http://testanything.org
[tap-difflet]: https://github.com/namuol/tap-difflet


Authors
-------

Turnt is by [Adrian Sampson][adrian] and [Alexa VanHattum][alexa].
We made it to test various research compilers in [Capra][].
The license is [MIT][].

[adrian]: https://www.cs.cornell.edu/~asampson/
[alexa]: https://www.cs.cornell.edu/~avh/
[capra]: https://capra.cs.cornell.edu
[mit]: https://opensource.org/licenses/MIT
