Tiny Unified Runner N' Tester (Turnt)
=====================================

Turnt is a simple snapshot testing tool inspired by [Cram][] and [LLVM's lit][lit].
It's good for testing things that translate text files to other text files, like compilers.
The idea is that each test is one input file, and you want to run a command and check that it still matches the saved output file.

To use it:

1. *Configure.*
   Decide what command you want to test.
   Make a `turnt.toml` config file and put `command = "mycmd {filename}"` in it to pass each test file as an argument to `mycmd`.
2. *Create a test.*
   Just write an input file next to your `turnt.toml`.
   We'll call it `foo.t`.
3. *Take a snapshot.*
   Run `turnt --save foo.t` to execute `mycmd foo.t` and save the standard output into `foo.out`.
   You might want to take a look at this output to make sure it's what you expect.
   Then you check both the input `foo.t` and output `foo.out` into version control.
4. *Test your work.*
   Now that you have a test in place, keep working.
   Use `turnt *.t` to run all your tests and confirm that the output still matches.
   If there's a mismatch, you can do `turnt --diff` to see the changes.
   (Or if you're confident, try `turnt --save` followed by `git diff`.)

Turnt's philosophy is to minimize the effort it takes to write new tests so you can quickly build up lots of them.
You don't write any custom logic to check results; you just record the complete "golden" output for each test.

Compared to ordinary unit testing, "snapshot" tests incur the mental effort of manually inspecting diffs when things change.
In return, it's easier to expand test coverage.
Snapshots also act as a crude form of documentation because every test is a complete, valid input to your program.

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

Turnt looks for a configuration file called `turnt.toml` in any of the ancestor directories of your test.
It can be alongside the test file or in any containing directory.
These options are available in `turnt.toml`:

- `command`.
  This is a shell command to run for each test input.
  The working directory for the command is the location of the `turnt.toml` configuration file, if any.
  If there's no configuration file, then it's the location of the test file itself.
- `output`.
  This is a mapping from extensions to output files to collect from each test.
  For example, use `output.txt = "my_output.txt"` to collect `my_output.txt` after each text extension and save it in `<test-name>.txt`.
  Use `-` to indicate the command's standard output and `2` to indicate its standard error.
  The default is like `output.out = "-"`, i.e., capture stdout and save it in `<test-name>.out`.
  You can include this yourself or omit if if you want to ignore the standard output.
- `return_code`.
  The expected exit status for the command. By default, 0.
- `diff`.
  The command to use for `turnt --diff` output.
  The default is `diff --new-file --unified`.
  Try `git --no-pager diff --no-index` to get colorful output.

Equivalently, you can embed options in test files themselves:

- `CMD: <command>` overrides `command` from the configuration.
- `OUT: <ext> <filename>` overrides `output` from the configuration.
  You can specify multiple files this way: one line per file.
- `ARGS: <arguments>`. Add arguments to a configured command (see below).
- `RETURN: <code>`. The expected exit status.

In commands and filenames, you can use certain patterns that get substituted with details about the tests:

- `{filename}`: The name of the test file, relative to the command working directory.
- `{base}`: Just the basename of the test file (no extension).
- `{args}`: Extra arguments specified using `ARGS:` in the test file.

If you need multiple files for a test, you can use a directory instead of a file.
Outputs will be placed *inside* the test directory instead of adjacent to it.
Output filenames will be like `out.ext` inside that directory.
There are two configurations just for dealing with directory tests:

- `out_base`.
  The basename for output files in directory tests: by default, `out`.
- `opts_file`.
  The filename to read inside of a directory test to parse inline options.


Command Line
------------

These are the command-line options:

- `--save`: Bless the current output from each test as the "correct" output, saving it to the output file that you'll want to check into version control.
- `--diff`: Show diffs between the actual and expected output for each test.
- `--verbose` or `-v`: Disable Turnt's default behavior where it will suppress test commands' stderr output. The result is more helpful but harder to read.
- `--print` or `-p`: Instead of checking test results, just run the command and show the output directly. This can be useful (especially in combination with `-v`) when iterating on a test interactively.
- `--args` or `-a`: Override the `args` string that gets interpolated into commands, which normally comes from in-file comments.
- `--config` or `-c`: Look for this config filename instead of the default `turnt.toml`.


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
