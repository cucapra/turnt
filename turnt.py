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

__version__ = '0.0.1'

CONFIG_FILENAME = 'turnt.toml'
DIFF_CMD = ['diff', '--new-file']


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


def get_command(config, path):
    """Get the shell command to run for a given test, as a string.
    """
    # Parse options from the test file.
    with open(path) as f:
        contents = f.read()
    cmd = extract_single_option(contents, 'cmd') or config['command']
    args = extract_single_option(contents, 'args') or ''

    # Construct the command.
    filename = os.path.basename(path)
    base, _ = os.path.splitext(filename)
    return cmd.format(
        filename=shlex.quote(filename),
        base=shlex.quote(base),
        args=args,
    )


def format_path_configs(name, path):
    """Format filename and base in a given name
    """
    filename = os.path.basename(path)
    base, _ = os.path.splitext(filename)
    return name.format(
        filename=shlex.quote(filename),
        base=shlex.quote(base)
    )


def get_out_files(config, path):
    """Get the mapping from saved output files to expected output files
    for the test.
    """
    with open(path) as f:
        contents = f.read()
    outputs = extract_options(contents, 'out')

    if outputs:
        outputs = {k: v for k, v in (o.split() for o in outputs)}
    elif "output" in config:
        outputs = config["output"]
    else:
        # If no outputs given anywhere, assume standard out.
        outputs = {"out": "-"}

    base, _ = os.path.splitext(path)
    base += "."

    return {base + k: format_path_configs(v, path)
            for (k, v) in outputs.items()}


def get_absolute_path(name, path):
    """Get the full absolute path for a user-provided name
    """
    return os.path.join(os.path.abspath(os.path.dirname(path)), name)


def check_result(name, idx, save, diff, proc, out_files):
    # If the command has a non-zero exit code, fail.
    if proc.returncode != 0:
        print('not ok {} - {}'.format(idx, name))
        print('# exit code: {}'.format(proc.returncode))
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            sys.stderr.buffer.flush()
        return False

    # Check whether outputs match.
    success = True
    for saved_file, output_file in out_files.items():
        # Diff the actual & expected output.
        if diff:
            subprocess.run(DIFF_CMD + [saved_file, output_file])

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
        line += ' # skip: updated {}'.format(list(out_files.keys()))
    print(line)

    return success


def run_test(path, idx, save, diff, verbose):
    config = load_config(path)
    cmd = get_command(config, path)
    out_files = get_out_files(config, path)

    # Run the command.
    with tempfile.NamedTemporaryFile(delete=False) as stdout:
        proc = subprocess.run(
            cmd,
            shell=True,
            stdout=stdout,
            stderr=None if verbose else subprocess.PIPE,
            cwd=os.path.abspath(os.path.dirname(path)),
        )

    try:
        # Get full paths. Special case: map "-" to standard out.
        out_files = {k: stdout.name if v == "-"
                     else get_absolute_path(v, path)
                     for (k, v) in out_files.items()}

        return check_result(path, idx, save, diff, proc, out_files)
    finally:
        os.unlink(stdout.name)


@click.command()
@click.option('--save', is_flag=True, default=False,
              help='Save new outputs (overwriting old).')
@click.option('--diff', is_flag=True, default=False,
              help='Show a diff between the actual and expected output.')
@click.option('-v', '--verbose', is_flag=True, default=False,
              help='Do not suppress stderr from successful commands.')
@click.argument('file', nargs=-1, type=click.Path(exists=True))
def turnt(file, save, diff, verbose):
    if file:
        print('1..{}'.format(len(file)))

    success = True
    for idx, path in enumerate(file):
        success &= run_test(path, idx + 1, save, diff, verbose)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    turnt()
