Turnt Changelog
===============

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
