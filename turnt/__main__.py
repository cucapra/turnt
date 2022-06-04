from typing import List, Optional
import click
import sys
from .config import Config
from .run import run_tests

CONFIG_NAME = 'turnt.toml'


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
