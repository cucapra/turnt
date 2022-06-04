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


Configuring
-----------

Turnt looks for a configuration file called `turnt.toml` in any of the ancestor directories of your test file.
It can be alongside the test file or in any containing directory.
It's a [TOML][] file that looks like something this:

    command = "mycmd {args} < {filename}"
    return_code = 42
    output.txt = "result.txt"

### `command`

Set `command` to a shell command to run on a given test file.
This is the only setting that is truly required.

The command is a [template][str.format]; Turnt will fill in these values:

- `{filename}`: The path to the test file, relative to the working directory.
- `{base}`: The basename of the test file, with the extension removed.
- `{args}`: Some extra arguments that the test or user provides.
  (See the `ARGS:` override and the `--args` command-line option below.)

The working directory for the command is the location of the `turnt.toml` configuration file, if any.
If there's no configuration file, then it's the location of the test file itself.

### `return_code`

By default, Turnt expects the test command to succeed, i.e., exit with status code 0.
Set `return_code` to a different status if you expect failure.

### `output`

By default, Turnt captures the standard output stream from your test command.
If your command produces other output files "on the side" or you want to capture the standard error stream, you can configure the `output` table.

`output` is a mapping from *snapshot extensions* to *collected filenames*.
For example, this TOML configuration:

    output.txt = "result.txt"

means that running the command will produce a file called `result.txt`, and we want to save that file in a snapshot called `<test-name>.txt`.

In place of a filename, use `-` to indicate the command's standard output and `2` to indicate its standard error.
The default behaves like this configuration:

    output.out = "-"

which captures stdout and saves it in `<test-name>.out`.
Defining `output` in `turnt.toml` disables this default behavior; you can include it explicitly if you want it alongside other outputs.


Per-Test Overrides
------------------

Sometimes you need to alter the setup for a specific test file.
Turnt looks for some overrides embedded in the test file itself: for example, you might put them in a comment at the top of a test program.

Put these things into your test file to override the configuration:

- `CMD: <command>` overrides `command` from the configuration.
- `ARGS: <arguments>` adds arguments to a configured command.
  Turnt puts this string in where the command uses `{args}`.
- `OUT: <ext> <filename>` overrides `output` from the configuration.
  You can specify multiple files this way: one line per file.
- `RETURN: <code>` overrides the expected exit status.


Directory Tests
---------------

A Turnt test is usually just a single input file, but you can also organize multiple related files into a directory.
Use the directory the same way as you would a single file:
pass its path to the `turnt` command, and the path will appear as the `{filename}` for the configured command.
So you might configure your test command like this:

    command = "mycmd {filename}/test.c"

if you want each test directory to contain a file called `test.c`.

Turnt puts snapshots *inside* the test directory instead of adjacent to it.
It names them `out.<extension>` in that directory.

There are two configuration options just for dealing with directory tests:

- `out_base`.
  The basename for output files in directory tests: by default, `out`.
- `opts_file`.
  The filename to read inside of a directory test to search for embedded overrides.
  In our above example, you could set this to `test.c` to look for `ARGS:` and friends in that file, or `opts.txt` to look for them in a separate file on the side.

[toml]: https://github.com/toml-lang/toml
[str.format]: https://docs.python.org/3/library/string.html#formatstrings


Command-Line Interface
----------------------

The most common `turnt` command-line options you'll need while running and updating tests are:

- `--save`: Bless the current output from each test as the "correct" output, saving it to the output file that you'll want to check into version control.
- `--diff`: Show diffs between the actual and expected output for each test.

You also might enjoy:

- `--parallel` or `-j`: Run your tests faster using parallel threads.

These options are useful when working with one specific test file:

- `--verbose` or `-v`: Disable Turnt's default behavior where it will suppress test commands' stderr output. The result is more helpful but harder to read.
- `--print` or `-p`: Instead of checking test results, just run the command and show the output directly. This can be useful (especially in combination with `-v`) when iterating on a test interactively.
- `--args` or `-a`: Override the `{args}` string in the test command.

This option lets you switch between different test environments:

- `--config` or `-c`: Look for this config filename instead of the default `turnt.toml`.


TAP
---

Turnt outputs results in the machine-readable [TAP][] format.
To make the output more pleasant to read, you can pipe it into a tool like [tap-difflet][], [tap-dot][], or [faucet][]:

    $ npm install -g tap-difflet
    $ turnt *.t | tap-difflet

[tap]: http://testanything.org
[tap-difflet]: https://github.com/namuol/tap-difflet
[tap-dot]: https://github.com/scottcorgan/tap-dot
[faucet]: https://github.com/substack/faucet


Credits
-------

Turnt is by [Adrian Sampson][adrian] and [Alexa VanHattum][alexa].
We made it to test various research compilers in [Capra][].
The license is [MIT][].

[adrian]: https://www.cs.cornell.edu/~asampson/
[alexa]: https://www.cs.cornell.edu/~avh/
[capra]: https://capra.cs.cornell.edu
[mit]: https://opensource.org/licenses/MIT
