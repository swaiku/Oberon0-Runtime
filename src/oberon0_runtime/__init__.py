# SPDX-FileCopyrightText: 2026 Jacques Supcik <jacques.supcik@hefr.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon0 runtime for WASM module
"""

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from wasmtime import (
    Func,
    FuncType,
    Global,
    GlobalType,
    Instance,
    Limits,
    Memory,
    MemoryType,
    Module,
    Store,
    ValType,
)

__version__ = "0.1.4"

INT32_SIZE = 4
INITIAL_STACK_POINTER = 1 << 16


class _ReturnCode(Enum):
    SUCCESS = 0
    FILE_NOT_FOUND = 1
    COMMAND_NOT_FOUND = 2
    NO_MORE_INPUT = 3


app = typer.Typer(
    help="Oberon0 runtime for WebAssembly modules - execute WASM files compiled from Oberon0 code."
)
console = Console()


@dataclass
class _Context:
    """
    Shared context for the runtime functions.
    """

    store: None | Store = None
    buffer: list[int] = field(default_factory=list)
    memory: None | Memory = None


context = _Context()


# Runtime functions
def _open_input() -> None:
    """open-inout is a no-op for compatibility with the original Oberon0 runtime."""
    logger.debug("OpenInput()")


def _read_int(address: int) -> None:
    """Reads an integer from the input buffer and store it in the memory
    at the given address."""
    logger.debug(f"ReadInt({address})")
    try:
        val = context.buffer.pop(0)
    except IndexError:
        console.print("[bold red]Error: no more input[/bold red]")
        raise typer.Exit(code=_ReturnCode.NO_MORE_INPUT.value) from None

    assert context.memory is not None
    assert context.store is not None
    _ = context.memory.write(
        context.store, val.to_bytes(INT32_SIZE, "little", signed=True), address
    )


def _eot() -> int:
    """Check if there are still elements in the input buffer."""
    logger.debug("EOT()")
    return 1 if len(context.buffer) == 0 else 0


def _write_char(c: int) -> None:
    """
    Write a character to the standard output.
    """
    logger.debug(f"WriteChar({c})")
    console.print(chr(c), end="")


def _write_int(i: int, len: int) -> None:
    """Write an integer to the standard output using a width of `len` characters
    (padded with spaces).
    """
    logger.debug(f"WriteInt({i}, {len})")
    console.print(f"{i:{len}d}", end="")


def _write_ln() -> None:
    """Write a newline character to the standard output."""
    console.print()


# Main function
@app.command()
def info(
    wasm_file: Annotated[typer.FileBinaryRead, typer.Argument()],
) -> None:
    """
    Print the list of commands available in the given WASM file.
    """
    store = Store()
    engine = store.engine
    try:
        module = Module(engine, wasm_file.read())
    except FileNotFoundError:
        console.print(
            f"[bold red]Error: WASM file '{wasm_file.name}' not found[/bold red]"
        )
        raise typer.Exit(code=_ReturnCode.FILE_NOT_FOUND.value) from None

    commands: list[str] = [
        f"- {str(i.name)}" for i in module.exports if isinstance(i.type, FuncType)
    ]

    panel = Panel(
        "\n".join(commands),
        title=f"[bold green]Commands available in '{wasm_file.name}'[/bold green]",
        border_style="green",
    )
    console.print(panel)


@app.command()
def version() -> None:
    """
    Print the version of the runtime.
    """
    console.print(f"[bold green]{__version__}[/bold green]")


@app.command()
def run(
    wasm_file: Annotated[typer.FileBinaryRead, typer.Argument()],
    command: Annotated[str, typer.Argument()],
    numbers: Annotated[list[int] | None, typer.Argument()] = None,
    debug: bool = False,
) -> None:
    """
    Run the given command from the given WASM file with the provided input numbers.
    """
    logger.remove()
    if debug:
        _ = logger.add(sys.stdout, level="DEBUG")
    else:
        _ = logger.add(sys.stdout, level="INFO")

    if numbers is not None:
        context.buffer.extend(numbers)

    context.store = Store()

    try:
        module = Module(context.store.engine, wasm_file.read())
    except FileNotFoundError:
        print(f"[bold red]Error: WASM file '{wasm_file.name}' not found[/bold red]")
        raise typer.Exit(code=_ReturnCode.FILE_NOT_FOUND.value) from None

    f_open_input = Func(context.store, FuncType([], []), _open_input)
    f_read_int = Func(context.store, FuncType([ValType.i32()], []), _read_int)
    f_eot = Func(context.store, FuncType([], [ValType.i32()]), _eot)
    f_write_char = Func(context.store, FuncType([ValType.i32()], []), _write_char)
    f_write_int = Func(
        context.store, FuncType([ValType.i32(), ValType.i32()], []), _write_int
    )
    f_write_ln = Func(context.store, FuncType([], []), _write_ln)

    context.memory = Memory(context.store, MemoryType(Limits(1, None)))
    sp = Global(
        context.store, GlobalType(ValType.i32(), mutable=True), INITIAL_STACK_POINTER
    )

    instance = Instance(
        context.store,
        module,
        [
            f_open_input,
            f_read_int,
            f_eot,
            f_write_char,
            f_write_int,
            f_write_ln,
            context.memory,
            sp,
        ],
    )

    try:
        cmd = instance.exports(context.store)[command]
        if not isinstance(cmd, Func):
            print(f"[bold red]Error: '{command}' is not a callable function[/bold red]")
            raise typer.Exit(code=_ReturnCode.COMMAND_NOT_FOUND.value)
        cmd(context.store)
    except KeyError:
        print(f"[bold red]Error: command '{command}' not found[/bold red]")
        raise typer.Exit(code=_ReturnCode.COMMAND_NOT_FOUND.value) from None


if __name__ == "__main__":
    app()
