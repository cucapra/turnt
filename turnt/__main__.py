import argparse
import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent import futures
from typing import NamedTuple, List, Tuple, Dict, Iterator, Optional


if sys.version_info[:2] >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


CONFIG_NAME = 'turnt.toml'
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
DIFF_DEFAULT = 'diff --new-file --unified'
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
    envs: List[str]


class TestEnv(NamedTuple):
    """The configuration values describing how to treat tests.
    """
    name: Optional[str]
    default: bool
    command: Optional[str]  # Here, a template to be filled in.
    out_files: Dict[str, str]
    return_code: int
    out_base: str
    out_dir: str
    opts_file: Optional[str]
    diff_cmd: List[str]
    args: str
    binary: bool
    todo: bool


class Test(NamedTuple):
    """The configuration for running a specific test.
    """
    env_name: Optional[str]

    # The test file and its base directory.
    test_path: str
    config_dir: str

    # The test run's behavior.
    command: str
    out_files: Dict[str, str]
    return_code: int
    diff_cmd: List[str]
    todo: bool


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


def format_command(env: TestEnv, config_dir: str, path: str) -> str:
    """Get the shell command to run for a given test, as a string.
    """
    assert env.command, "no command specified"

    # Construct the command.
    filename = os.path.relpath(path, config_dir)
    base, _ = os.path.splitext(os.path.basename(filename))
    return env.command.format(
        filename=shlex.quote(filename),
        base=shlex.quote(base),
        args=env.args,
    )


def format_output_path(name: str, path: str) -> str:
    """Get the *actual* output path to be collected from a test run.

    This is the path that the command actually writes to, which we will
    then collect and compare to the expected output. `name` is the
    configured name; we substitute patterns in it and treat it relative
    to `path`, which is the test file. `name` could also indicate the
    stdout or stderr streams, in which case it is left unchanged.
    """
    if name in (STDOUT, STDERR):
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


def format_expected_path(env: TestEnv, ext: str, path: str) -> str:
    """Get the *expected* output file location for a test environment.

    `path` is the path to the test file itself. `ext` is the output
    extension key for a given environment.

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
        base = env.out_base
    else:
        dirname = os.path.dirname(path)
        filename = os.path.basename(path)
        base, _ = os.path.splitext(filename)

    # Optionally put the output files in a different (sub)directory.
    dirname = os.path.normpath(os.path.join(dirname, env.out_dir))

    return os.path.join(dirname, '{}.{}'.format(base, ext))


def get_out_files(env: TestEnv, path: str) -> Dict[str, str]:
    """Get a map from expected to actual output paths for a test.
    """
    return {
        format_expected_path(env, k, path):
        format_output_path(v, path)
        for (k, v) in env.out_files.items()
    }


def read_contents(env: TestEnv, path: str) -> str:
    """Load the contents of a test, from which we will parse options.

    We get the contents either from the file itself or, if the test is a
    directory, from a file contained therein.
    """
    if os.path.isfile(path):
        with open(path) as f:
            return f.read()
    else:
        if env.opts_file:
            opts_path = os.path.join(path, env.opts_file)
            try:
                with open(opts_path) as f:
                    return f.read()
            except IOError:
                return ''
        else:
            return ''


def load_config(path: str, config_name: str) -> Tuple[dict, str]:
    """Load the configuration TOML file for a test at the given path.

    Return the configuration data itself and the containing directory.
    """
    for dirpath in ancestors(path):
        config_path = os.path.join(dirpath, config_name)
        if os.path.isfile(config_path):
            with open(config_path, 'rb') as f:
                return tomllib.load(f), dirpath

    # No configuration; use defaults and embedded options only.
    return {}, os.path.dirname(os.path.abspath(path))


def get_env(config_data: dict, name: Optional[str] = None) -> TestEnv:
    """Get the settings from a configuration section.
    """
    return TestEnv(
        name=name,
        default=config_data.get('default', True),
        command=config_data.get('command'),
        out_files=config_data.get('output', {"out": STDOUT}),
        return_code=config_data.get('return_code', 0),
        diff_cmd=shlex.split(config_data.get('diff', DIFF_DEFAULT)),
        out_base=config_data.get("out_base", "out"),
        out_dir=config_data.get("out_dir", "."),
        opts_file=config_data.get("opts_file"),
        args='',
        binary=config_data.get('binary', False),
        todo=config_data.get('todo', False),
    )


def get_envs(config_base: dict, names: List[str]) -> Iterator[TestEnv]:
    """List the test environments described in a TOML config file.

    If `names` is empty, include all the environments where `default` is
    set. Otherwise, only include environments with matching names.
    """
    if 'envs' in config_base:
        # It's a multi-environment configuration. Ignore the "root" of
        # the config document and use `envs` exclusively.
        for name, env_data in config_base['envs'].items():
            if names and name not in names:
                continue
            env = get_env(env_data, name)
            if not names and not env.default:
                continue
            yield env
    else:
        # It's a single-environment configuration.
        if names and 'default' not in names:
            return
        env = get_env(config_base)
        if not names and not env.default:
            return
        yield env


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
    return options[0] if options else None


def override_env(env: TestEnv, contents: str) -> TestEnv:
    """Update a test environment using options embedded in a test file.
    """
    output_strs = extract_options(contents, 'out')
    outputs = {k: v for k, v in (o.split() for o in output_strs)}

    return_code = extract_single_option(contents, 'return')
    todo = extract_single_option(contents, 'todo')

    return env._replace(
        command=extract_single_option(contents, 'cmd') or env.command,
        out_files=outputs or env.out_files,
        args=extract_single_option(contents, 'args') or env.args,
        return_code=int(return_code) if return_code else env.return_code,
        todo=(todo == 'true') if todo else env.todo,
    )


def configure_test(cfg: Config, path: str) -> Iterator[Test]:
    """Get the configurations for a specific test file.

    This combines information from the configuration file and options
    embedded in the test file, which can override the former. The path
    need not exist or be a file. If it's a directory or does not exist,
    no options are extracted (and the defaults are used).
    """
    # Load base options from the configuration file.
    config, config_dir = load_config(path, cfg.config_name)

    # Configure each environment.
    for env in get_envs(config, names=cfg.envs):
        # Load the contents and extract overrides.
        if not env.binary:
            try:
                contents = read_contents(env, path)
            except UnicodeDecodeError:
                print(f'{path}: Could not decode text. '
                      'Consider setting `binary=true`.')
            else:
                env = override_env(env, contents)

        # Further override using the global configuration.
        if cfg.args is not None:
            env = env._replace(args=cfg.args)

        yield Test(
            env_name=env.name,
            test_path=path,
            command=format_command(env, config_dir, path),
            config_dir=config_dir,
            out_files=get_out_files(env, path),
            return_code=env.return_code,
            diff_cmd=env.diff_cmd,
            todo=env.todo,
        )


def map_outputs(test: Test, stdout: str, stderr: str) -> Test:
    """Update a test to reflect captured output streams.

    The Test keeps track of all the output files that need to be
    compared. This function lets a test runner supply the filenames for
    stdout/stderr captures, which don't have "real" filenames until
    after the test runs.
    """
    sugar = {STDOUT: stdout, STDERR: stderr}
    out_files = {k: sugar.get(v, v)
                 for (k, v) in test.out_files.items()}
    return test._replace(out_files=out_files)


def tap_line(ok: bool, idx: int, test: Test) -> str:
    """Format a TAP success/failure line."""
    return '{} {} - {}{}'.format(
        'ok' if ok else 'not ok',
        idx,
        test.test_path,
        ' {}'.format(test.env_name) if test.env_name else '',
    )


def check_result(cfg: Config, test: Test,
                 proc: subprocess.CompletedProcess,
                 idx: int) -> Tuple[bool, List[str]]:
    """Check the results of a single test and print the outcome.

    Return a bool indicating success and a TAP message.
    """
    # If the command has a non-zero exit code, fail.
    if proc.returncode != test.return_code:
        msg = [tap_line(False, idx, test)]
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
        if cfg.diff:
            subprocess.run(test.diff_cmd + [saved_file, output_file],
                           stdout=sys.stderr.buffer)

        # Read actual & expected output.
        with open(output_file, 'rb') as f:
            actual = f.read()
        if os.path.isfile(saved_file):
            with open(saved_file, 'rb') as f:
                expected = f.read()
        else:
            expected = None

        # Compare.
        if actual != expected:
            differing.append(saved_file)
        if expected is None:
            missing.append(saved_file)

    # Save the new output, if requested.
    update = cfg.save and differing
    if update:
        for saved_file, output_file in test.out_files.items():
            parent_dir = os.path.dirname(saved_file)
            if not os.path.isdir(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            shutil.copyfile(output_file, saved_file)

    # Show TAP success line with directives.
    line = tap_line(not differing, idx, test)
    directives = []
    if update:
        directives.append(
            'skip: updated {}'.format(', '.join(test.out_files.keys()))
        )

    # Mark "TODO" tests, i.e., allowed failures.
    success = not differing
    if test.todo:
        success = True
        if not update:
            directives.append('todo')

    diff_exist = [fn for fn in differing if fn not in missing]
    if diff_exist:
        directives.append('differing: {}'.format(', '.join(diff_exist)))
    if missing:
        directives.append('missing: {}'.format(', '.join(missing)))

    if directives:
        line += ' # ' + '; '.join(directives)
    return success, [line]


def run_test(cfg: Config, test: Test, idx: int) -> Tuple[bool, List[str]]:
    """Run a single test.

    Check the output and produce a TAP summary line, unless `dump` is
    enabled, in which case we just print the output. Return a bool
    indicating success and the message.
    """
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
            # copied from the temporary file to standard out.
            if cfg.verbose and not cfg.dump:
                with open(stderr.name) as f:
                    sys.stdout.write(f.read())

            # Supply outputs and check.
            test = map_outputs(test, stdout.name, stderr.name)
            return check_result(cfg, test, proc, idx)
        finally:
            os.unlink(stdout.name)
            os.unlink(stderr.name)


def load_tests(cfg: Config, paths: List[str]) -> Iterator[Test]:
    """Load all the tests to perform for each file.
    """
    for path in paths:
        yield from configure_test(cfg, path)


def run_tests(cfg: Config, parallel: bool, test_files: List[str]) -> bool:
    """Run all the tests in an entire suite, possibly in parallel.
    """
    tests = list(load_tests(cfg, test_files))
    if test_files and not cfg.dump:
        print('1..{}'.format(len(tests)))

    if parallel:
        # Parallel test execution.
        success = True
        with futures.ThreadPoolExecutor() as pool:
            futs = []
            for idx, path in enumerate(tests):
                futs.append(pool.submit(
                    run_test,
                    cfg, path, idx + 1
                ))
            for fut in futs:
                sc, msg = fut.result()
                success &= sc
                for line in msg:
                    print(line, flush=True)
        return success

    else:
        # Simple sequential loop.
        success = True
        for idx, path in enumerate(tests):
            sc, msg = run_test(cfg, path, idx + 1)
            success &= sc
            for line in msg:
                print(line, flush=True)
        return success


def readable_file(name: str) -> str:
    if os.path.isdir(name):
        return name
    with open(name, "r") as _:
        pass
    return name


def turnt() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--save",
        action="store_true",
        default=False,
        help="Save new outputs (overwriting old).",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Show a diff between the actual and expected output.",
    )
    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        default=False,
        help="Just show the command output (don't check anything).",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=CONFIG_NAME,
        help=f"Name of the config file. Default: {CONFIG_NAME}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Do not suppress stderr from successful commands.",
    )
    parser.add_argument(
        "-a",
        "--args",
        help="Override arguments for test commands.",
    )
    parser.add_argument(
        "-j",
        "--parallel",
        action="store_true",
        default=False,
        help="Run tests in parallel.",
    )
    parser.add_argument(
        "-e",
        "--env",
        nargs="+",
        help="The names of configured environment(s) to run.",
    )
    parser.add_argument("file", type=readable_file, nargs="+")
    args = parser.parse_args()
    cfg = Config(
        config_name=args.config,
        save=args.save,
        diff=args.diff,
        verbose=args.verbose,
        dump=args.print,
        args=args.args,
        envs=args.env,
    )
    success = run_tests(cfg, args.parallel, args.file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    turnt()
