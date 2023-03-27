from pathlib import Path
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import Section, SymbolTableSection
from elftools.elf.relocation import RelocationSection
from io import BytesIO
import argparse
import subprocess
import re

# https://github.com/vidstige/ar/
import ar


# https://refspecs.linuxbase.org/elf


def fix_reloc(bcodes, offset):
    offset *= 2
    for i in range(8):
        bcodes[offset + i] = '.'
    return bcodes


def to_pattern_str(hex_list):
    s = ''.join(hex_list).strip('.')
    for n in range(20, 0, -1):
        n *= 8
        s = s.replace('.' * n, '.' * (n // 2))
    s = re.sub(r'([0-9a-f]{2})', r'\\x\1', s)
    return s


def demangle(name):
    if name.startswith('_Z'):
        s = subprocess.check_output(['c++filt', '-p', name])
        return s.strip().decode('ascii')
    else:
        return name


def demangle_names(names):
    buf = '\n'.join(names).encode('ascii')
    proc = subprocess.run('c++filt -p', stdout=subprocess.PIPE, input=buf)
    output = proc.stdout.decode('ascii')
    sep = '\r\n' if '\r\n' in output else '\n'
    names = proc.stdout.decode('ascii').split(sep)
    return names


def find_functions(io):
    texts = {}  # key is section index, value is hex string
    symbols = []
    relocs = {}  # key is target section index, value is reloc section

    elf = ELFFile(io)
    for i, section in enumerate(elf.iter_sections()):
        if isinstance(section, SymbolTableSection):
            for symbol in section.iter_symbols():
                if symbol['st_info'].type in ('STT_FUNC', 'STT_LOPROC') and \
                        isinstance(symbol['st_shndx'], int) and \
                        not(len(symbol.name) == 2 and symbol.name.startswith('$')):
                    symbols.append(symbol)
        elif isinstance(section, RelocationSection):
            relocs[section['sh_info']] = section
        elif isinstance(section, Section):
            texts[i] = list(section.data().hex())

    for i, section in relocs.items():
        if i in texts:
            for reloc in section.iter_relocations():
                texts[i] = fix_reloc(texts[i], reloc['r_offset'])

    results = {}
    names = [s.name for s in symbols]
    names = demangle_names(names)
    for i, symbol in enumerate(symbols):
        start = symbol['st_value'] * 2
        if symbol['st_size'] > 0:
            end = start + symbol['st_size'] * 2
        else:
            end = None
        # print(symbol['st_shndx'], symbol.name, symbol['st_info'].type, symbol['st_size'])
        buf = to_pattern_str(texts[symbol['st_shndx']][start:end])
        if buf in results:
            results[buf] += f' / {names[i]}'
        else:
            results[buf] = names[i]

    return results


def update(io):
    global results
    for buf, name in find_functions(io).items():
        if buf in results:
            if name not in results[buf]:
                results[buf] += f' / {name}'
        else:
            results[buf] = name


def check_short(v):
    return not(len(v[0]) <= 8 * 4 and v[1].count('/') > 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', action='store', nargs=1)
    parser.add_argument('out_path', action='store', nargs='?')
    parser.add_argument('name', action='store', nargs='?')
    args = parser.parse_args()

    if args.out_path is None:
        out_path = Path(args.path[0]).name + '.txt'
    else:
        out_path = args.out_path

    if args.name is None:
        name = str(Path(out_path).stem)
    else:
        name = args.name

    results = {}
    for path in Path(args.path[0]).rglob('*'):
        if not path.is_file():
            continue
        print(path)
        if path.suffix == '.a':
            with open(path, 'rb') as fp:
                for archive in ar.Archive(fp):
                    # print(' ', archive.name)
                    update(BytesIO(archive.get_stream(fp).read()))
        elif path.suffix == '.o':
            update(open(path, 'rb'))

    db = list(filter(check_short, results.items()))
    db.sort(key=lambda x: len(x[0]), reverse=True)
    out = [name, ]
    for p, n in db:
        out.append(n)
        out.append(p)

    open(out_path, 'w').write('\n'.join(out))
