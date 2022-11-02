Turnt Changelog
===============

1.9.0 (2022-11-02)
------------------

- `-h` is now an alias for `--help`.
- `differing` and `missing` notes are now printed on the same line as the test itself, as TAP directives. This should both be easier to read when looking at the TAP output directly, and it should make life a bit simpler for TAP consumers.
- A new `binary` config option that disables looking with test files for (text) overrides. Even without this flag, binary files no longer crash Turnt altogether and instead merely log an error message.

1.8.0 (2022-06-07)
------------------

- Add support for multiple *test environments* that run different commands on the same file. This is especially useful for differential testing, when multiple commands have the same expected output.
- Flush the output buffer after every line, which makes streaming TAP consumers more useful.

1.7.0 (2022-06-03)
------------------

- Search for `turnt.toml` configuration files in ancestor directories, not just in the same directory as the test.
- The minimum Python version advanced to 3.6.
- Switch the TOML library to [tomli][] (or the standard library on Python 3.11+).

[tomli]: https://github.com/hukkin/tomli

1.6.0 (2022-06-01)
------------------

- Add comments to the TAP output to indicate detected output differences.
- Add a `--config` command-line option.

1.5.0 (2020-09-08)
------------------

- Run tests in parallel with `-j`.

1.4.0 (2020-07-01)
------------------

- Support options in directory tests (the `opts_file` config option).
- Outputs from directory tests go to `dirname/out.ext` instead of
  `dirname/dirname.ext`.

1.3.0 (2020-06-30)
------------------

- The diff command is now configurable.
- We use a unified diff by default.

1.2.0 (2019-09-24)
------------------

- A new `--args` option lets you override the `args` field that otherwise comes from in-file settings.
- You can now capture the standard error from a command. In the same way that the `-` pseudo-file indicates the standard output, `2` now indicates the standard error.
- Tests can now have (non-zero) expected return codes. Use `return_code` in the configuration file or `RETURN` in file comments.


1.1.0 (2019-09-12)
------------------

A new `--print` option enables a convenient mode for debugging tests that just shows the output instead of checking any results.


1.0.0 (2019-09-03)
------------------

Initial release.
