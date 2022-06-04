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
from typing import NamedTuple, List, Tuple, Dict, Iterator, Optional

__version__ = '1.7.0'

DIFF_DEFAULT = 'diff --new-file --unified'
CONFIG_NAME = 'turnt.toml'
STDOUT = '-'
STDERR = '2'


class Config(NamedTuple):
    """The setup for a test run (which consists of many tests).
    """
    config_name: str
    save: bool
    diff: bool
    verbose: bool
    dump: bool
    args: Optional[str]


class Test(NamedTuple):
    """The configuration for running a specific test.
    """
    cfg: Config
    test_path: str
    command: str
    config_dir: str
    out_files: Dict[str, str]
    return_code: int
    diff_cmd: List[str]


def ancestors(path: str) -> Iterator[str]:
    """Generate enclosing directories of a given path.

    We generate directory names "inside out" starting with the immediate
    parent directory (not `path` itself). The walk stops at any
    filesystem boundary.
    """
    path = os.path.abspath(path)
    while True:
        new_path = os.path.dirname(path)
        if new_path == path:
            break
        path = new_path

        yield path
        if os.path.ismount(path):
            break


def load_config(path: str, config_name: str) -> Tuple[dict, str]:
    """Load the configuration for a test at the given path.

    Return the configuration value itself and the containing directory.
    """
    for dirpath in ancestors(path):
        config_path = os.path.join(dirpath, config_name)
        if os.path.isfile(config_path):
            with open(config_path) as f:
                return dict(tomlkit.loads(f.read())), dirpath

    # No configuration; use defaults and embedded options only.
    return {}, os.path.dirname(os.path.abspath(path))


def extract_options(text: str, key: str) -> List[str]:
    """Parse a config option(s) from the given text.

    Options are embedded in declarations like "KEY: value" that may
    occur anywhere in the file. We take all the text after "KEY: " until
    the end of the line. Return the value strings as a list.
    """
    regex = r'\b{}:\s+(.*)'.format(key.upper())
    return re.findall(regex, text)


def extract_single_option(text: str, key: str) -> Optional[str]:
    """Parse a single config option from the given text.

    The format is the same as for `extract_options`, but we return only
    the first value---or None if there are no instances.
    """
    options = extract_options(text, key)
    if options:
        return options[0]
    else:
        return None


def get_command(config: dict, config_dir: str, path: str, contents: str,
                args: Optional[str]) -> str:
    """Get the shell command to run for a given test, as a string.
    """
    cmd = extract_single_option(contents, 'cmd') or config['command']
    args = args or extract_single_option(contents, 'args') or ''

    # Construct the command.
    filename = os.path.relpath(path, config_dir)
    base, _ = os.path.splitext(os.path.basename(filename))
    return cmd.format(
        filename=shlex.quote(filename),
        base=shlex.quote(base),
        args=args,
    )


def format_output_path(name: str, path: str) -> str:
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


def format_expected_path(ext: str, path: str, out_base: str) -> str:
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


def get_out_files(config: dict, path: str, contents: str) -> Dict[str, str]:
    """Get the mapping from saved output files to expected output files
    for the test.
    """
    # Get the mapping from extensions to output files.
    output_strs = extract_options(contents, 'out')
    if output_strs:
        outputs = {k: v for k, v in (o.split() for o in output_strs)}
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


def get_return_code(config: dict, contents: str) -> int:
    return_code = extract_single_option(contents, 'return')

    if return_code:
        return int(return_code)
    elif "return_code" in config:
        return int(config["return_code"])
    else:
        return 0


def configure_test(cfg: Config, path: str) -> Test:
    """Get the configuration for a specific test.

    This combines information from the configuration file and options
    embedded in the test file, which can override the former. The path
    need not exist or be a file. If it's a directory or does not exist,
    no options are extracted (and the defaults are used).

    `args` can override the arguments for the command, which otherwise
    come from the file itself.
    """
    # Load base options from the configuration file.
    config, config_dir = load_config(path, cfg.config_name)

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

    return Test(
        cfg,
        path,
        get_command(config, config_dir, path, contents, cfg.args),
        config_dir,
        get_out_files(config, path, contents),
        get_return_code(config, contents),
        shlex.split(config.get('diff', DIFF_DEFAULT)),
    )


def check_result(test: Test,
                 proc: subprocess.CompletedProcess,
                 idx: int) -> Tuple[bool, List[str]]:
    """Check the results of a single test and print the outcome.

    Return a bool indicating success and a TAP message.
    """
    # If the command has a non-zero exit code, fail.
    if proc.returncode != test.return_code:
        msg = ['not ok {} - {}'.format(idx, test.test_path)]
        if test.return_code:
            msg.append('# exit code: {}, expected: {}'.format(
                proc.returncode, test.return_code,
            ))
        else:
            msg.append('# exit code: {}'.format(proc.returncode))
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            sys.stderr.buffer.flush()
        return False, msg

    # Check whether outputs match.
    differing = []
    missing = []
    for saved_file, output_file in test.out_files.items():
        # Diff the actual & expected output.
        if test.cfg.diff:
            subprocess.run(test.diff_cmd + [saved_file, output_file])

        # Read actual & expected output.
        with open(output_file) as f:
            actual = f.read()
        if os.path.isfile(saved_file):
            with open(saved_file) as f:
                expected = f.read()
        else:
            expected = None

        # Compare.
        if actual != expected:
            differing.append(saved_file)
        if expected is None:
            missing.append(saved_file)

    # Save the new output, if requested.
    update = test.cfg.save and differing
    if update:
        for saved_file, output_file in test.out_files.items():
            shutil.copy(output_file, saved_file)

    # Show TAP success line and annotations.
    line = '{} {} - {}'.format(
        'ok' if not differing else 'not ok',
        idx,
        test.test_path,
    )
    if update:
        line += ' # skip: updated {}'.format(', '.join(test.out_files.keys()))

    diff_exist = [fn for fn in differing if fn not in missing]
    if diff_exist:
        line += '\n# differing: {}'.format(', '.join(diff_exist))
    if missing:
        line += '\n# missing: {}'.format(', '.join(missing))

    return not differing, [line]


def run_test(cfg: Config, path: str, idx: int) -> Tuple[bool, List[str]]:
    """Run a single test.

    Check the output and produce a TAP summary line, unless `dump` is
    enabled, in which case we just print the output. Return a bool
    indicating success and the message.
    """
    test = configure_test(cfg, path)

    # Show the command if we're dumping the output.
    if cfg.dump:
        print('$', test.command, file=sys.stderr)

    with contextlib.ExitStack() as stack:
        # Possibly use a temporary file for the output.
        if not cfg.dump:
            stdout = tempfile.NamedTemporaryFile(delete=False)
            stderr = tempfile.NamedTemporaryFile(delete=False)
            stack.enter_context(stdout)
            stack.enter_context(stderr)

        # Run the command.
        proc = subprocess.run(
            test.command,
            shell=True,
            stdout=None if cfg.dump else stdout,
            stderr=None if cfg.dump else stderr,
            cwd=test.config_dir,
        )

    # Check results.
    if cfg.dump:
        return proc.returncode == 0, []
    else:
        try:
            # If we're in verbose but not dump/print mode, errors need to be
            # copied from the temporary file to standard out
            if cfg.verbose and not cfg.dump:
                with open(stderr.name) as f:
                    sys.stdout.write(f.read())

            # Replace shorthands with the standard output/error files.
            sugar = {STDOUT: stdout.name, STDERR: stderr.name}
            out_files = {k: sugar.get(v, v)
                         for (k, v) in test.out_files.items()}
            test = test._replace(out_files=out_files)

            return check_result(test, proc, idx)
        finally:
            os.unlink(stdout.name)
            os.unlink(stderr.name)


def run_tests(cfg: Config, parallel: bool, test_files: List[str]) -> bool:
    """Run all the tests in an entire suite, possibly in parallel.
    """
    if test_files and not cfg.dump:
        print('1..{}'.format(len(test_files)))

    if parallel:
        # Parallel test execution.
        success = True
        with futures.ThreadPoolExecutor() as pool:
            futs = []
            for idx, path in enumerate(test_files):
                futs.append(pool.submit(
                    run_test,
                    cfg, path, idx + 1
                ))
            for fut in futs:
                sc, msg = fut.result()
                success &= sc
                for line in msg:
                    print(line)
        return success

    else:
        # Simple sequential loop.
        success = True
        for idx, path in enumerate(test_files):
            sc, msg = run_test(cfg, path, idx + 1)
            success &= sc
            for line in msg:
                print(line)
        return success


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
@click.option('-c', '--config', default=CONFIG_NAME,
              help=f'Name of the config file. Default: {CONFIG_NAME}')
@click.argument('file', nargs=-1, type=click.Path(exists=True))
def turnt(file: List[str], save: bool, diff: bool, verbose: bool, dump: bool,
          args: Optional[str], parallel: bool, config: str) -> None:
    cfg = Config(
        config_name=config,
        save=save,
        diff=diff,
        verbose=verbose,
        dump=dump,
        args=args,
    )
    success = run_tests(cfg, parallel, file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    turnt()
