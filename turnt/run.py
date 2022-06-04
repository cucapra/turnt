"""Run configured tests.
"""
import os
import subprocess
import tempfile
import shutil
import sys
import contextlib
from concurrent import futures
from typing import List, Tuple
from .config import Config, Test, configure_test, STDOUT, STDERR


def check_result(test: Test,
                 proc: subprocess.CompletedProcess) -> Tuple[bool, List[str]]:
    """Check the results of a single test and print the outcome.

    Return a bool indicating success and a TAP message.
    """
    # If the command has a non-zero exit code, fail.
    if proc.returncode != test.return_code:
        msg = ['not ok {} - {}'.format(test.idx, test.test_path)]
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
        test.idx,
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
    test = configure_test(cfg, path, idx)

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

            return check_result(test, proc)
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
