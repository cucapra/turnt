"""Run configured tests.
"""
import os
import subprocess
import tempfile
import shutil
import sys
import contextlib
from concurrent import futures
from typing import List, Tuple, Iterator
from .config import Config, Test, configure_test, map_outputs, default_files


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
    # Use the default test file list, if no specific tests are specified.
    if not test_files:
        test_files = default_files(cfg)

    # The TAP header.
    if cfg.dump:
        print('1..{}'.format(len(test_files)))

    if parallel:
        # Parallel test execution.
        success = True
        with futures.ThreadPoolExecutor() as pool:
            futs = []
            for idx, path in enumerate(load_tests(cfg, test_files)):
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
        for idx, path in enumerate(load_tests(cfg, test_files)):
            sc, msg = run_test(cfg, path, idx + 1)
            success &= sc
            for line in msg:
                print(line, flush=True)
        return success
