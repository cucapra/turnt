Tiny Unified Runner N' Tester (Turnt)
=====================================

Turnt is a simple testing tool inspired by [Cram][] and [LLVM's lit][lit].
The idea is that each test consists of two files: an input file and an output file.
You want to run a command on the input file and check that the output is equal to the expected output file.

To use it:

1. Create a `turnt.toml` configuration file in your tests directory.
   It currently only has one option: `command`, which should be the shell command to run.
   In the command, `{filename}` is substituted for the test input file.
2. Write a test (the input file).
3. Get the initial output.
   Run `turnt --save foo.ext` to generate the expected output in `foo.out`.
   You'll want to check this output into your repository.
4. Run the tests.
   Use `turnt foo.ext` to check a test output.
   If a test fails, add `--diff` to compare the actual and expected outputs.

[cram]: https://bitheap.org/cram/
[lit]: https://llvm.org/docs/CommandGuide/lit.html


Install
-------

This is a Python 3 tool.
To install it, we use [Flit][]:

    $ pip install --user flit

Here's a quick way to install the tool with a symlink:

    $ flit install --symlink --user

[flit]: https://flit.readthedocs.io/en/latest/


TAP
---

Turnt outputs [TAP][] results by default.
To make the output more pleasant to read, you can pipe it into a tool like [tap-difflet][]:

    $ npm install -g tap-difflet
    $ turnt *.t | tap-difflet

[tap]: http://testanything.org
[tap-difflet]: https://github.com/namuol/tap-difflet
