"""Define the configuration for tests.
"""
from typing import NamedTuple, List, Tuple, Dict, Iterator, Optional
import shlex
import re
import os
import sys
if sys.version_info[:2] >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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
    opts_file: Optional[str]
    diff_cmd: List[str]
    args: str
    binary: bool


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


def get_out_files(env: TestEnv, path: str) -> Dict[str, str]:
    """Get the mapping from saved output files to expected output files
    for the test.
    """
    return {format_expected_path(k, path, env.out_base):
            format_output_path(v, path)
            for (k, v) in env.out_files.items()}


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
        opts_file=config_data.get("opts_file"),
        args='',
        binary=config_data.get('binary', False),
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

    return env._replace(
        command=extract_single_option(contents, 'cmd') or env.command,
        out_files=outputs or env.out_files,
        args=extract_single_option(contents, 'args') or env.args,
        return_code=int(return_code) if return_code else env.return_code,
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
