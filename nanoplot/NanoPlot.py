#! /usr/bin/env python
# wdecoster
'''
The main purpose of this script is to create plots for nanopore data.
Input data can be given as
-compressed, standard or streamed fastq file
-compressed, standard or streamed fastq file with additional information added by albacore or MinKNOW
-a bam file
-a summary file generated by albacore
'''


from __future__ import division, print_function
import argparse
import sys
import os
import time
import logging
import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from multiprocessing import cpu_count
from scipy import stats
import pysam
import nanoget
import nanoplotter
import nanomath
from .version import __version__


def main():
	'''
	Organization function
	-setups logging
	-gets inputdata
	-calls plotting function
	'''
	try:
		args = getArgs()
		if not os.path.exists(args.outdir):
			os.makedirs(args.outdir)
		stamp = initlogs(time.time(), args)
		datadf, lengthprefix, logBool, readlengthsPointer, stamp = getInput(stamp, args)
		makePlots(datadf, lengthprefix, logBool, readlengthsPointer, args, stamp)
		logging.info("Succesfully processed all input.")
	except Exception as e:
		logging.error(e, exc_info=True)
		raise


def getArgs():
	parser = argparse.ArgumentParser(description="Perform diagnostic plotting, QC analysis Nanopore sequencing data and alignments.")
	parser.add_argument("-v", "--version",
						help="Print version and exit.",
						action="version",
						version='NanoPlot {}'.format(__version__))
	parser.add_argument("-t", "--threads",
						help="Set the allowed number of threads to be used by the script",
						default=4,
						type=int)
	parser.add_argument("--maxlength",
						help="Drop reads longer than length specified.",
						type=int)
	parser.add_argument("--drop_outliers",
						help="Drop outlier reads with extreme long length.",
						action="store_true")
	parser.add_argument("--downsample",
						help="Reduce dataset to N reads by random sampling.",
						type=int)
	parser.add_argument("--loglength",
						help="Logarithmic scaling of lengths in plots.",
						action="store_true")
	parser.add_argument("--alength",
						help="Use aligned read lengths rather than sequenced length (bam mode)",
						action="store_true")
	parser.add_argument("-o", "--outdir",
						help="Specify directory in which output has to be created.",
						default=".")
	parser.add_argument("-t", "--prefix",
						help="Specify an optional prefix to be used for the output files.",
						default="",
						type=str)
	target = parser.add_mutually_exclusive_group(required=True)
	target.add_argument("--fastq",
						help="Data is in default fastq format.")
	target.add_argument("--fastq_rich",
						help="Data is in fastq format generated by albacore or MinKNOW with additional information concerning channel and time.")
	target.add_argument("--summary",
						help="Data is a summary file generated by albacore.")
	target.add_argument("--bam",
						help="Data as a sorted bam file.")
	return parser.parse_args()


def initlogs(time0, args):
	try:
		start_time = datetime.datetime.fromtimestamp(time0).strftime('%Y%m%d_%H%M')
		logging.basicConfig(
			format='%(asctime)s %(message)s',
			filename=os.path.join(args.outdir, args.prefix + "Nanoplot_" + start_time + ".log"),
			level=logging.INFO)
	except IOError:
		sys.exit("ERROR: No writing permission to the directory.")
	logging.info('Nanoplot {} started with arguments {}'.format(__version__, args))
	logging.info("{} cpu's are available".format(cpu_count()))
	logging.info('Versions of key modules are:')
	for module in [np, sns, pd, pysam, nanoget, nanoplotter, nanomath]:
		logging.info('{}: {}'.format(module, module.__version__))
	return time0


def getInput(stamp, args):
	'''
	Get input and process accordingly. 	Data can be:
	-a uncompressed, bgzip, bzip2 or gzip compressed fastq file
	-s sorted bam file
	Handle is passed to the proper functions to get DataFrame with metrics
	'''
	if args.fastq:
		datadf = nanoget.processFastqPlain(args.fastq)
	elif args.bam:
		datadf = nanoget.processBam(args.bam, min(cpu_count() - 1, args.threads))
	elif args.fastq_rich:
		datadf = nanoget.processFastq_rich(args.fastq_rich)
	elif args.summary:
		datadf = nanoget.processSumary(args.summary)
	stamp = timeStamp(stamp, "Gathering data")
	datadf, lengthprefix, logBool, readlengthsPointer = filterData(datadf, args)
	return (datadf, lengthprefix, logBool, readlengthsPointer, stamp)


def filterData(datadf, args):
	'''
	Perform filtering on the data based on arguments set on commandline
	- use alighned length or sequenced length (bam mode only)
	- drop outliers
	- drop reads longer than args.maxlength
	- use log10 scaled reads
	- downsample reads to args.downsample
	Return an accurate prefix which is added to plotnames using this filtered data
	'''
	lengthprefix = []
	if args.alength and args.bam:
		readlengthsPointer = "aligned_lengths"
		lengthprefix.append("Aligned_")
		logging.info("Using aligned read lengths for plotting.")
	else:
		readlengthsPointer = "lengths"
		logging.info("Using sequenced read lengths for plotting.")
	if args.drop_outliers:
		datadf=nanomath.removeLengthOutliers(datadf, readlengthsPointer)
		lengthprefix.append("OutliersRemoved_")
		logging.info("Removing length outliers for plotting.")
	if args.maxlength:
		datadf=datadf[datadf[readlengthsPointer] < args.maxlength]
		lengthprefix.append("MaxLength-" + str(args.maxlength) + '_')
		logging.info("Removing reads longer than {}.".format(str(args.maxlength)))
	if args.loglength:
		datadf["log_" + readlengthsPointer] = np.log10(datadf[readlengthsPointer])
		readlengthsPointer = "log_" + readlengthsPointer
		lengthprefix.append("Log_")
		logging.info("Using Log10 scaled read lengths.")
		logBool = True
	else:
		logBool = False
	if args.downsample:
		newNum = min(args.downsample, len(datadf.index))
		lengthprefix.append("Downsampled_")
		logging.info("Downsampling the dataset from {} to {} reads".format(len(datadf.index), newNum))
		datadf = datadf.sample(newNum)
	return(datadf, ''.join(lengthprefix), logBool, readlengthsPointer)


def timeStamp(start, task):
	now = time.time()
	logging.info("Task {0} took {1:.2f} seconds".format(task, now - start))
	return now


def makePlots(datadf, lengthprefix, logBool, readlengthsPointer, args, stamp):
	'''Call plotting functions'''
	nanoplotter.lengthPlots(
		array=datadf[readlengthsPointer],
		name="Read length",
		path=os.path.join(args.outdir, args.prefix + lengthprefix),
		n50=nanomath.getN50(np.sort(datadf["lengths"])),
		log=logBool)
	stamp = timeStamp(stamp, "Creating length plots")
	nanoplotter.scatter(
		x=datadf[readlengthsPointer],
		y=datadf["quals"],
		names=['Read lengths', 'Average read quality'],
		path=os.path.join(args.outdir, args.prefix + lengthprefix + "LengthvsQualityScatterPlot"),
		log=logBool)
	stamp = timeStamp(stamp, "Creating LengthvsQual plot")
	if args.fastq_rich or args.summary:
		nanoplotter.spatialHeatmap(
			array=datadf["channelIDs"],
			title="Number of reads generated per channel",
			path=os.path.join(args.outdir, args.prefix + "ActivityMap_ReadsPerChannel"),
			colour="Greens")
		stamp = timeStamp(stamp, "Creating spatialheatmap for succesfull basecalls")
		nanoplotter.timePlots(
			df=datadf,
			path=os.path.join(args.outdir, args.prefix))
		stamp = timeStamp(stamp, "Creating timeplots")
	if args.bam:
		nanoplotter.scatter(
			x=datadf["aligned_lengths"],
			y=datadf["lengths"],
			names=["Aligned read lengths", "Sequenced read length"],
			path=os.path.join(args.outdir, args.prefix + "AlignedReadlengthvsSequencedReadLength"))
		stamp = timeStamp(stamp, "Creating AlignedLengthvsLength plot")
		nanoplotter.scatter(
			x=datadf["mapQ"],
			y=datadf["quals"],
			names=["Read mapping quality", "Average basecall quality"],
			path=os.path.join(args.outdir, args.prefix + "MappingQualityvsAverageBaseQuality"))
		stamp = timeStamp(stamp, "Creating MapQvsBaseQ plot")
		nanoplotter.scatter(
			x=datadf[readlengthsPointer],
			y=datadf["mapQ"],
			names=["Read length", "Read mapping quality"],
			path=os.path.join(args.outdir, args.prefix + lengthprefix + "MappingQualityvsReadLength"),
			log=logBool)
		stamp = timeStamp(stamp, "Creating MapQvsBaseQ plot")
		minPID = np.amin(datadf["percentIdentity"])
		nanoplotter.scatter(
			x=datadf["percentIdentity"],
			y=datadf["aligned_quals"],
			names=["Percent identity", "Read quality"],
			path=os.path.join(args.outdir, args.prefix + "PercentIdentityvsAverageBaseQuality"),
			stat=stats.pearsonr,
			minvalx=minPID)
		stamp = timeStamp(stamp, "Creating PIDvsBaseQ plot")
		nanoplotter.scatter(
			x=datadf[readlengthsPointer],
			y=datadf["percentIdentity"],
			names=["Aligned read length", "Percent identity"],
			path=os.path.join(args.outdir, args.prefix + "PercentIdentityvsAlignedReadLength"),
			stat=stats.pearsonr,
			log=logBool,
			minvaly=minPID)
		stamp = timeStamp(stamp, "Creating PIDvsLength plot")


if __name__ == "__main__":
	main()
