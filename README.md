Tiny Unified Runner N' Tester (Turnt)
=====================================

Turnt is a simple testing tool inspired by [Cram][] and [LLVM's lit][lit].
The idea is that each test consists of two or more files: an input file and output file(s).
You want to run a command on the input file and check that the output is equal to the expected output file(s).

To use it:

1. Optionally, create a `turnt.toml` configuration file in your tests directory.
   `{filename}` is substituted for the test input file.
   If you need it, `{base}` is the filename without the extension. 
   The main option, `command`, should be the shell command to run.  
   The optional `output` lets you specify custom output files as `output.<extension> = <filename>`. 
   For example, `output.txt = "my_output.txt"` specifies that the contents of the file `my_output.txt` should be saved as `{base}.txt`, and compared against on subsequent runs. 
   The character `-` can be used on the right hand side to specify standard out (thus, `output.out = "-"` specifies the default behavior, but can be omitted if standard out should be ignored).
2. Write a test (the input file).
   Optionally, include a comment somewhere in the test file like `CMD: <your command here>` to override the configured command with a new one for this test.
   You can also use `ARGS: <something>` to specify extra arguments, which will get substituted for `{args}` in the test command. 
   You can specify custom output files with `OUT: <extension> <filename>` (one line per file).
3. Get the initial output.
   Run `turnt --save foo.ext` to generate the expected output in (by default) `foo.out` and/or any custom output files.
   You'll want to check these output files into your repository.
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
