"""Turnt is a simple expect-style testing tool for command-line
programs.
"""
import click
import tomlkit
import os
import shlex
import subprocess
import tempfile
import shutil
import sys
import re
import contextlib
from concurrent import futures

__version__ = '1.5.0'

CONFIG_FILENAME = 'turnt.toml'
DIFF_DEFAULT = 'diff --new-file --unified'
STDOUT = '-'
STDERR = '2'


def load_config(path):
    """Load the configuration for a test at the given path.
    """
    parent = os.path.dirname(path)
    config_path = os.path.join(parent, CONFIG_FILENAME)
    if os.path.isfile(config_path):
        with open(config_path) as f:
            return tomlkit.loads(f.read())
    else:
        return {}


def extract_options(text, key):
    """Parse a config option(s) from the given text.

    Options are embedded in declarations like "KEY: value" that may
    occur anywhere in the file. We take all the text after "KEY: " until
    the end of the line. Return the value strings as a list.
    """
    regex = r'\b{}:\s+(.*)'.format(key.upper())
    return re.findall(regex, text)


def extract_single_option(text, key):
    """Parse a single config option from the given text.

    The format is the same as for `extract_options`, but we return only
    the first value---or None if there are no instances.
    """
    options = extract_options(text, key)
    if options:
        return options[0]
    else:
        return None


def get_command(config, path, contents, args=None, err=None):
    """Get the shell command to run for a given test, as a string.
    """
    cmd = extract_single_option(contents, 'cmd') or config['command']
    args = args or extract_single_option(contents, 'args') or ''

    # Construct the command.
    filename = os.path.basename(path)
    base, _ = os.path.splitext(filename)
    return cmd.format(
        filename=shlex.quote(filename),
        base=shlex.quote(base),
        args=args,
    )


def format_output_path(name, path):
    """Substitute patterns in configured *actual* output filenames and
    produce a complete path (relative to `path`, which is the test
    file).
    """
    if name == STDOUT or name == STDERR:
        return name

    filename = os.path.basename(path)
    base, _ = os.path.splitext(filename)
    return os.path.join(
        os.path.dirname(path),
        name.format(
            filename=filename,
            base=shlex.quote(base),
        )
    )


def format_expected_path(ext, path, out_base):
    """Generate the location to use for the *expected* output file for a
    given test `path` and output extension key `ext`.

    The resulting path is located "next to" the test file, using its
    basename with a different extension---for example `./foo/bar.t`
    becomes `./foo/bar.ext`. If the test path is a directory, the file is
    placed *inside* this directory, and `out_base` is used for the filename
    instead of the test name (e.g., `./foo/bar.t/out_base.ext`).
    """
    # When the test is a directory, place results there and use
    # `out_base`. Otherwise, when the test is a file, put results
    # *alongside* the file, in the same parent directory, and use the
    # test filename to generate the output filename (ignoring
    # `out_base`).
    if os.path.isdir(path):
        dirname = path
        base = out_base
    else:
        dirname = os.path.dirname(path)
        filename = os.path.basename(path)
        base, _ = os.path.splitext(filename)

    return os.path.join(dirname, '{}.{}'.format(base, ext))


def get_out_files(config, path, contents):
    """Get the mapping from saved output files to expected output files
    for the test.
    """
    outputs = extract_options(contents, 'out')

    # Get the mapping from extensions to output files.
    if outputs:
        outputs = {k: v for k, v in (o.split() for o in outputs)}
    elif "output" in config:
        outputs = config["output"]
    else:
        # If no outputs given anywhere, assume standard out.
        outputs = {"out": STDOUT}

    # Get the base to use for directory test outputs.
    out_base = config.get("out_base", "out")

    return {format_expected_path(k, path, out_base):
            format_output_path(v, path)
            for (k, v) in outputs.items()}


def get_return_code(config, contents):
    return_code = extract_single_option(contents, 'return')

    if return_code:
        return int(return_code)
    elif "return_code" in config:
        return int(config["return_code"])
    else:
        return 0


def load_options(config, path, args=None):
    """Extract the options embedded in the test file, which can override
    the options in the configuration. Return the test command and an
    output file mapping.

    The path need not exist or be a file. If it's a directory or does
    not exist, no options are extracted (and the defaults are used).

    `args` can override the arguments for the command, which otherwise
    come from the file itself.
    """
    # Load the contents for option parsing either from the file itself
    # or, if the test is a directory, from a file contained therein.
    if os.path.isfile(path):
        with open(path) as f:
            contents = f.read()
    else:
        if 'opts_file' in config:
            opts_path = os.path.join(path, config['opts_file'])
            try:
                with open(opts_path) as f:
                    contents = f.read()
            except IOError:
                contents = ''
        else:
            contents = ''

    return (
        get_command(config, path, contents, args),
        get_out_files(config, path, contents),
        get_return_code(config, contents),
    )


def check_result(name, idx, save, diff, proc, out_files, return_code,
                 diff_cmd):
    """Check the results of a single test and print the outcome. Return
    a bool indicating success and a TAP message as a list of strings.
    """
    # If the command has a non-zero exit code, fail.
    if proc.returncode != return_code:
        msg = ['not ok {} - {}'.format(idx, name)]
        if return_code:
            msg.append('# exit code: {}, expected: {}'.format(proc.returncode,
                                                              return_code))
        else:
            msg.append('# exit code: {}'.format(proc.returncode))
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            sys.stderr.buffer.flush()
        return False, msg

    # Check whether outputs match.
    success = True
    for saved_file, output_file in out_files.items():
        # Diff the actual & expected output.
        if diff:
            subprocess.run(diff_cmd + [saved_file, output_file])

        # Read actual & expected output and compare.
        with open(output_file) as f:
            actual = f.read()
        if os.path.isfile(saved_file):
            with open(saved_file) as f:
                expected = f.read()
        else:
            expected = None
        success &= actual == expected

    # Save the new output, if requested.
    update = save and not success
    if update:
        for saved_file, output_file in out_files.items():
            shutil.copy(output_file, saved_file)

    # Show TAP success line.
    line = '{} {} - {}'.format('ok' if success else 'not ok', idx, name)
    if update:
        line += ' # skip: updated {}'.format(', '.join(out_files.keys()))

    return success, [line]


def run_test(path, idx, save, diff, verbose, dump, args=None):
    """Run a single test.

    Check the output and produce a TAP summary line, unless `dump` is
    enabled, in which case we just print the output. Return a bool
    indicating success and the message as a list of strings.
    """
    config = load_config(path)
    cmd, out_files, return_code = load_options(config, path, args)
    diff_cmd = shlex.split(config.get('diff', DIFF_DEFAULT))

    # Show the command if we're dumping the output.
    if dump:
        print('$', cmd, file=sys.stderr)

    with contextlib.ExitStack() as stack:
        # Possibly use a temporary file for the output.
        if not dump:
            stdout = tempfile.NamedTemporaryFile(delete=False)
            stderr = tempfile.NamedTemporaryFile(delete=False)
            stack.enter_context(stdout)
            stack.enter_context(stderr)

        # Run the command.
        proc = subprocess.run(
            cmd,
            shell=True,
            stdout=None if dump else stdout,
            stderr=None if dump else stderr,
            cwd=os.path.abspath(os.path.dirname(path)),
        )

    # Check results.
    if dump:
        return proc.returncode == 0, []
    else:
        try:
            # If we're in verbose but not dump/print mode, errors need to be
            # copied from the temporary file to standard out
            if verbose and not dump:
                with open(stderr.name) as f:
                    sys.stdout.write(f.read())

            # Replace shorthands with the standard output/error files.
            sugar = {STDOUT: stdout.name, STDERR: stderr.name}
            out_files = {k: sugar.get(v, v) for (k, v) in out_files.items()}

            return check_result(path, idx, save, diff, proc, out_files,
                                return_code, diff_cmd)
        finally:
            os.unlink(stdout.name)
            os.unlink(stderr.name)


@click.command()
@click.option('--save', is_flag=True, default=False,
              help='Save new outputs (overwriting old).')
@click.option('--diff', is_flag=True, default=False,
              help='Show a diff between the actual and expected output.')
@click.option('-p', '--print', 'dump', is_flag=True, default=False,
              help="Just show the command output (don't check anything).")
@click.option('-v', '--verbose', is_flag=True, default=False,
              help='Do not suppress stderr from successful commands.')
@click.option('-a', '--args',
              help='Override arguments for test commands.')
@click.option('-j', '--parallel',
              help='Run tests in parallel.')
@click.argument('file', nargs=-1, type=click.Path(exists=True))
def turnt(file, save, diff, verbose, dump, args, parallel):
    if file and not dump:
        print('1..{}'.format(len(file)))

    success = True
    if parallel:
        # Parallel test execution.
        with futures.ThreadPoolExecutor() as pool:
            futs = []
            for idx, path in enumerate(file):
                futs.append(pool.submit(
                    run_test,
                    path, idx + 1, save, diff, verbose, dump, args
                ))
            for fut in futs:
                sc, msg = fut.result()
                success &= sc
                for line in msg:
                    print(line)

    else:
        # Simple sequential loop.
        for idx, path in enumerate(file):
            sc, msg = run_test(path, idx + 1, save, diff, verbose, dump, args)
            success &= sc
            for line in msg:
                print(line)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    turnt()
