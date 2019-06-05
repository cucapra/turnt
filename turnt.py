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

__version__ = '0.0.1'

CONFIG_FILENAME = 'turnt.toml'


def load_config(path):
    """Load the configuration for a test at the given path.
    """
    parent = os.path.dirname(path)
    config_path = os.path.join(parent, CONFIG_FILENAME)
    if os.path.isfile(config_path):
        with open(config_path) as f:
            return tomlkit.loads(f.read())
    else:
        return None


def get_command(config, path):
    """Get the command to run for a given test.
    """
    parts = shlex.split(config['command'])
    return [
        p.format(filename=os.path.basename(path))
        for p in parts
    ]


def get_out_file(config, path):
    """Get the filename containing the expected output for a test.
    """
    base, _ = os.path.splitext(path)
    return '{}.out'.format(base)


def run_test(path, idx, save, diff, tap, verbose):
    config = load_config(path)
    cmd = get_command(config, path)
    out_path = get_out_file(config, path)

    # Run the command.
    with tempfile.NamedTemporaryFile(delete=False) as out, \
        tempfile.NamedTemporaryFile(delete=False) as err:
        completed = subprocess.run(
            cmd,
            stdout=out,
            stderr=err,
            cwd=os.path.abspath(os.path.dirname(path)),
        )

    try:
        # If the command has a non-zero exit code, fail.
        if completed.returncode != 0:
            with open(err.name) as f:
                cmd_err = f.read()
                print('not ok - error code {}'.format(completed.returncode))
                print(cmd_err, file=sys.stderr)
                return False

        # Output error, if requested.
        if verbose:
            with open(err.name) as f:
                cmd_err = f.read()
                if cmd_err:
                    print(cmd_err, file=sys.stderr)

        # Diff the actual & expected output.
        if diff:
            subprocess.run(['diff', '--new-file', out_path, out.name])

        # Save the new output, if requested.
        if save:
            shutil.copy(out.name, out_path)

        # Check whether output matches & summarize.
        with open(out.name) as f:
            actual = f.read()
        if os.path.isfile(out_path):
            with open(out_path) as f:
                expected = f.read()
        else:
            expected = None
        success = actual == expected

        if tap:
            print('{} {} - {}'.format(
                'ok' if success else 'not ok',
                idx,
                path,
            ))

    finally:
        os.unlink(out.name)
        os.unlink(err.name)

    return success


@click.command()
@click.option('--save', is_flag=True, default=False,
              help='Save new outputs (overwriting old).')
@click.option('--diff', is_flag=True, default=False,
              help='Show a diff between the actual and expected output.')
@click.option('--tap/--no-tap', default=True,
              help='Summarize test success in TAP format.')
@click.option('-v', '--verbose', is_flag=True, default=False,
              help='Do not suppress command stderr output.')
@click.argument('file', nargs=-1, type=click.Path(exists=True))
def turnt(file, save, diff, tap, verbose):
    if tap and file:
        print('1..{}'.format(len(file)))

    success = True
    for idx, path in enumerate(file):
        success &= run_test(path, idx + 1, save, diff, tap, verbose)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    turnt()
