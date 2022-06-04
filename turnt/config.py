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


class Test(NamedTuple):
    """The configuration for running a specific test.
    """
    # About the batch this test belongs to.
    cfg: Config
    idx: int

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


def load_config(path: str, config_name: str) -> Tuple[dict, str]:
    """Load the configuration for a test at the given path.

    Return the configuration value itself and the containing directory.
    """
    for dirpath in ancestors(path):
        config_path = os.path.join(dirpath, config_name)
        if os.path.isfile(config_path):
            with open(config_path, 'rb') as f:
                return tomllib.load(f), dirpath

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


def read_contents(config: dict, path: str) -> str:
    """Load the contents of a test, from which we will parse options.

    We get the contents either from the file itself or, if the test is a
    directory, from a file contained therein.
    """
    if os.path.isfile(path):
        with open(path) as f:
            return f.read()
    else:
        if 'opts_file' in config:
            opts_path = os.path.join(path, config['opts_file'])
            try:
                with open(opts_path) as f:
                    return f.read()
            except IOError:
                return ''
        else:
            return ''


def configure_test(cfg: Config, path: str, idx: int) -> Test:
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

    # Load the contents for overrides.
    contents = read_contents(config, path)

    return Test(
        cfg=cfg,
        idx=idx,
        test_path=path,
        command=get_command(config, config_dir, path, contents, cfg.args),
        config_dir=config_dir,
        out_files=get_out_files(config, path, contents),
        return_code=get_return_code(config, contents),
        diff_cmd=shlex.split(config.get('diff', DIFF_DEFAULT)),
    )
