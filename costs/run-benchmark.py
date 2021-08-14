import glob
import subprocess
import sys
import os
import argparse
import pathlib
import re
import shutil
import datetime
from typing import List, Union, IO, Dict

open_files: Dict[str, Union[int, IO]] = {}
grep_string = ''
counter = 0
force_run = False
dir_path = pathlib.Path(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')).resolve()
backend = 'python'
overwrite = False
number_of_try = 1
only_heaviest = False
now = str(datetime.datetime.now())


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

    file_already_exists = os.path.isfile(full_path)
    file_handle: Union[int, IO] = 1
    if not dry_run:
        file_handle = open(to_os_path(full_path), 'w' if overwrite else 'a')

    open_files[full_path] = file_handle

    if dry_run:
        return file_handle

    if not file_already_exists or overwrite:
        file_handle.write('time,env,file,cost,assemble_from_ir,to_sexp_f,run_program,multiplier,n\n')

    return file_handle


def find_heaviest_benchmark_files(directory):
    is_apply = os.path.split(directory)[1] == 'apply'
    clvm_files = glob.glob('%s/*.clvm' % directory)
    if is_apply:
        return clvm_files[0]

    regex = re.compile('(.+)-([0-9]+)-([0-9]+)[.]clvm')
    obj = {}
    for i in range(len(clvm_files)):
        fn = clvm_files[i]
        filename = os.path.split(fn)[1]
        match = regex.match(filename)
        if not match:
            continue
        name = match[1]
        n_bytes = int(match[2])
        n = int(match[3])
        if name not in obj:
            obj[name] = {
                'max_bytes': n_bytes,
                'max_n': n,
                'heaviest_i': i,
            }
        elif n_bytes >= obj[name]['max_bytes'] and n >= obj[name]['max_n']:
            obj[name]['max_bytes'] = n_bytes
            obj[name]['max_n'] = n
            obj[name]['heaviest_i'] = i

    heaviest_i_all = [obj[v]['heaviest_i'] for v in obj]
    return [clvm_files[i] for i in heaviest_i_all]


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

    counter += 1

    # if we have a csv file for this run already, skip running it again
    dry_run = not force_run and os.path.split(fn)[1].split('-')[0] in existing_results
    if dry_run:
        print('%04d: %s SKIPPED' % (counter, fn))
        return

    counters = {}
    print('%04d: %s' % (counter, fn))

    matcher = re.compile('(.+)[:=](.+)')

    # the filename is expected to be in the form:
    # name "-" value_size "-" num_calls
    env = open(fn[:-4] + 'env').read()
    subprocess_args = ['brun', '--backend=%s' % backend, '-c', '--quiet', '--time', to_os_path(fn), env]
    for i in range(number_of_try):
        output = subprocess.check_output(subprocess_args)
        output = output.decode('ascii').splitlines()[:-1]
        for o in output:
            r = matcher.match(o)
            if r:
                key = r.group(1).strip()
                value = float(r.group(2).strip())
                counters[key] = (counters[key] if key in counters else 0) + value
            else:
                print('ERROR parsing: %s' % o)

    for key in counters:
        counters[key] /= number_of_try

    print(counters)

    name_components = filename.split('-')
    f = get_file(folder, '-'.join(name_components[0:-1]), dry_run)
    line = \
        now + ',' + \
        ('clvm_tools(Python)-clvm(%s)' % ('python' if backend == 'Python' else 'Rust')) + ',' + \
        filename + ',' + \
        str(counters['cost']) + ',' + \
        str(counters['assemble_from_ir']) + ',' + \
        str(counters['to_sexp_f']) + ',' + \
        str(counters['run_program']) + ',' + \
        name_components[-1].split('.')[0] + ',' + \
        str(number_of_try) + '\n'
    f.write(line)


def run_benchmark_folder(directory: str):
    global open_files
    existing_results = []
    for r in glob.glob(directory + '/*.csv'):
        existing_results.append(os.path.split(r)[1].split('-')[1])

    heaviest_benchmark_files = find_heaviest_benchmark_files(directory)
    for fn in glob.glob('%s/*.clvm' % directory):
        if only_heaviest and fn not in heaviest_benchmark_files:
            continue
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
    parser.add_argument('-b', '--backend', default='python',
                        help='rust/python')
    parser.add_argument('-w', '--overwrite', action='store_true',
                        help='Overwrite previous benchmark result if it exists')
    parser.add_argument('-n', '--number-of-try', type=int, default=1,
                        help='Number of benchmark iterations for accurate benchmark result')
    parser.add_argument('-o', '--only-heaviest', action='store_true',
                        help='Run only the heaviest benchmark for each benchmark type')
    args = parser.parse_args(args=sys.argv[1:])

    if args.force:
        force_run = True
    if args.grep:
        grep_string = args.grep
    if args.backend and args.backend == 'rust':
        backend = 'rust'
    if args.overwrite:
        overwrite = True
    number_of_try = args.number_of_try
    if args.only_heaviest:
        only_heaviest = True

    root_dir = '%s/test-programs' % dir_path
    if args.root_dir:
        root_dir = args.root_dir
    root_dir = to_posix_path(root_dir)

    run_all_benchmark(root_dir)
