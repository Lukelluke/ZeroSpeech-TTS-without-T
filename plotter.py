# -*- coding: utf-8 -*- #
"""*********************************************************************************************"""
#   FileName     [ plotter.py ]
#   Synopsis     [ code used to generate plots ]
#   Author       [ Ting-Wei Liu (Andi611) ]
#   Copyright    [ Copyleft(c), NTUEE, NTU, Taiwan ]
"""*********************************************************************************************"""


###############
# IMPORTATION #
###############
import os
import csv
import argparse
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size': 17})

###########
# LAMBDAS #
###########
to_str = lambda x: [str(i) for i in x]
norm = lambda x : np.interp(x, (np.amin(x), np.amax(x)), (0, +1))


##################
# CONFIGURATIONS #
##################
def get_config():
	parser = argparse.ArgumentParser(description='plotter arguments')
	parser.add_argument('--result_dir', type=str, default='./result/plots/', help='directory to save plots')

	mode_args = parser.add_argument_group('mode')
	mode_args.add_argument('--all', action='store_true', help='plot all curve')
	mode_args.add_argument('--tradeoff', action='store_true', help='plot trade-off curve')
	mode_args.add_argument('--encoding', action='store_true', help='plot encoding curve')

	args = parser.parse_args()
	return args


##################
# PLOT TRADE OFF #
##################
def plot_tradeoff(wer, br, name):
	plt.figure(figsize=(9, 5))
	plt.xlabel('Bit Rate')
	plt.ylabel('WER')
	plt.gca().invert_xaxis()
	# plt.xscale('log')
	plt.plot(to_str(br), wer, linestyle=':', marker='o', color='red')
	plt.savefig(name)
	plt.close()


##################
# PLOT TRADE OFF #
##################
def plot_encoding(wer, br, dim, name):
	plt.figure(figsize=(9, 5))
	plt.ylabel('Linear Interpolated WER and Bit Rate')
	plt.xlabel('Embedding Size')
	plt.plot(to_str(dim), norm(wer), linestyle=':', marker='o', color='m', label='wer')
	plt.plot(to_str(dim), norm(br), linestyle=':', marker='o', color='c', label='br')
	plt.legend(loc='center right')
	plt.tight_layout()
	plt.savefig(name)
	plt.close()


########
# MAIN #
########
"""
    main function
"""
def main():
	args = get_config()
	os.makedirs(args.result_dir, exist_ok=True)

	
	wer = [0.196, 0.313, 0.430, 0.629, 0.717, 0.797, 0.887, 0.998, 0.998, 1.000, 1.000]
	br = [138.54, 138.45, 135.45, 138.45, 138.35, 134.80, 105.96, 61.79, 55.97, 48.78, 41.32]
	dim = [1024, 512, 256, 128, 64, 32, 16, 8, 7, 6, 5]

	if args.all or args.tradeoff:
		plot_tradeoff(wer, br, os.path.join(args.result_dir, 'tradeoff.png'))
	if args.all or args.encoding:
		plot_encoding(wer, br, dim, os.path.join(args.result_dir, 'encoding.png'))


if __name__ == '__main__':
	main()