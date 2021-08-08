import glob
import subprocess
import sys
import os
import argparse
import pathlib
import re
import shutil
from typing import List, Union, IO, Dict

open_files: Dict[str, Union[int, IO]] = {}
grep_string = ''
counter = 0
force_run = False
dir_path = pathlib.Path(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')).resolve()


def to_posix_path(os_path: str):
    if os.name == 'nt':
        return pathlib.PureWindowsPath(os_path).as_posix().replace('C:', '')
    return os_path


def to_os_path(posix_path: str):
    if os.name == 'nt':
        return 'C:' + posix_path.replace('/', '\\')
    return posix_path


def get_file(folder: str, name: str, dry_run: bool):
    full_path = os.path.join(folder, 'results-%s.csv' % name)
    if full_path in open_files:
        return open_files[full_path]

    file_handle: Union[int, IO] = 1
    if not dry_run:
        file_handle = open(to_os_path(full_path), 'a')

    open_files[full_path] = file_handle

    if dry_run:
        return file_handle

    file_handle.write('#cost,assemble_from_ir,to_sexp_f,run_program,multiplier\n')
    return file_handle


def try_run_gnuplot(gnuplot_filename: str):
    if shutil.which('gnuplot'):
        os.system('gnuplot %s' % gnuplot_filename)


def generate_and_run_gnuplot(directory: str):
    gnuplot_filename = '%s/render-timings.gnuplot' % directory
    gnuplot_file = open(to_os_path(gnuplot_filename), 'w+')

    gnuplot_file.write('''set output "%s/timings.png"
    set datafile separator ","
    set term png size 1400,900 small
    set termoption enhanced
    set ylabel "run-time (s)"
    set xlabel "number of ops"
    set xrange [0:*]
    set yrange [0:0.3]
    ''' % directory)

    color = 0
    gnuplot_file.write('plot ')
    count = len(open_files)
    for n, v in open_files.items():
        cont = ', \\'
        if color + 1 == count:
            cont = ''
        name = n.split('results-')[1].split('.csv')[0]
        gnuplot_file.write('"%s" using 5:4 with points lc %d title "%s"%s\n' % (to_os_path(n), color, name, cont))
        color += 1
        if not isinstance(v, int):
            v.close()

    gnuplot_file.close()
    try_run_gnuplot(gnuplot_filename)


def run_benchmark_file(fn: str, existing_results: List[str]):
    global counter
    folder, filename = os.path.split(fn)

    if grep_string and not re.match(grep_string, filename):
        return

    # if we have a csv file for this run already, skip running it again
    dry_run = not force_run and os.path.split(fn)[1].split('-')[0] in existing_results

    if not dry_run:
        print('%04d: %s' % (counter, fn))

    counter += 1
    counters = {}

    # the filename is expected to be in the form:
    # name "-" value_size "-" num_calls
    if not dry_run:
        env = open(fn[:-4] + 'env').read()
        output = subprocess.check_output(['brun', '--backend=rust', '-c', '--quiet', '--time', to_os_path(fn), env])
        output = output.decode('ascii').split('\n', 5)[:-1]

        for o in output:
            try:
                if ':' in o:
                    key, value = o.split(':')
                    counters[key.strip()] = value.strip()
                elif '=' in o:
                    key, value = o.split('=')
                    counters[key.strip()] = value.strip()
            except BaseException as e:
                print(e)
                print('ERROR parsing: %s' % o)
        print(counters)

    name_components = filename.split('-')
    f = get_file(folder, '-'.join(name_components[0:-1]), dry_run)
    if not dry_run:
        line = counters['cost'] + ',' + \
               counters['assemble_from_ir'] + ',' + \
               counters['to_sexp_f'] + ',' + \
               counters['run_program'] + ',' + \
               name_components[-1].split('.')[0] + '\n'
        f.write(line)


def run_benchmark_folder(directory: str):
    global open_files
    existing_results = []
    for r in glob.glob(directory + '/*.csv'):
        existing_results.append(os.path.split(r)[1].split('-')[1])

    for fn in glob.glob('%s/*.clvm' % directory):
        run_benchmark_file(fn, existing_results)

    generate_and_run_gnuplot(directory)
    open_files = {}


def run_all_benchmark(benchmark_root: str):
    for directory in glob.glob('%s/*' % benchmark_root):
        run_benchmark_folder(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run benchmark')
    parser.add_argument('-r', '--root-dir', type=pathlib.Path,
                        help='Root folder of benchmark files')
    parser.add_argument('-g', '--grep',
                        help='grep string applied to benchmark file name')
    parser.add_argument('-f', '--force', action='store_true',
                        help='Run even if result file exists')
    args = parser.parse_args(args=sys.argv[1:])

    if args.force:
        force_run = True

    if args.grep:
        grep_string = args.grep

    root_dir = '%s/test-programs' % dir_path
    if args.root_dir:
        root_dir = args.root_dir
    root_dir = to_posix_path(root_dir)

    run_all_benchmark(root_dir)
