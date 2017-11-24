#! /usr/bin/env python
# wdecoster

'''
The main purpose of this script is to create plots for nanopore data.
Input data can be given as one or multiple of:
-compressed, standard or streamed fastq file
-compressed, standard or streamed fastq file, with
 additional information added by albacore or MinKNOW
-a bam file
-a summary file generated by albacore
'''


from argparse import ArgumentParser
from os import path
import logging
from nanoget import get_input
import nanomath
import numpy as np
from scipy import stats
import nanoplot.utils as utils
from .version import __version__
import nanoplotter
import pickle
from textwrap import wrap


def main():
    '''
    Organization function
    -setups logging
    -gets inputdata
    -calls plotting function
    '''
    args = get_args()
    try:
        utils.make_output_dir(args.outdir)
        logfile = utils.init_logs(args)
        args.format = nanoplotter.check_valid_format(args.format)
        settings = vars(args)
        settings["path"] = path.join(args.outdir, args.prefix)
        sources = [args.fastq, args.bam, args.fastq_rich, args.fastq_minimal, args.summary]
        sourcename = ["fastq", "bam", "fastq_rich", "fastq_minimal", "summary"]
        if args.pickle:
            datadf = pickle.load(open(args.pickle, 'rb'))
        else:
            datadf = get_input(
                source=[n for n, s in zip(sourcename, sources) if s][0],
                files=[f for f in sources if f][0],
                threads=args.threads,
                readtype=args.readtype,
                combine="simple",
                barcoded=args.barcoded)
        if args.store:
            pickle.dump(
                obj=datadf,
                file=open(settings["path"] + "NanoPlot-data.pickle", 'wb'))
        if args.raw:
            datadf.to_csv("NanoPlot-data.tsv.gz", sep="\t", index=False, compression="gzip")
        statsfile = settings["path"] + "NanoStats.txt"
        nanomath.write_stats(
            datadfs=[datadf],
            outputfile=statsfile)
        logging.info("Calculated statistics")
        datadf, settings = filter_data(datadf, settings)
        if args.barcoded:
            barcodes = list(datadf["barcode"].unique())
            statsfile = settings["path"] + "NanoStats_barcoded.txt"
            nanomath.write_stats(
                datadfs=[datadf[datadf["barcode"] == b] for b in barcodes],
                outputfile=statsfile,
                names=barcodes)
            plots = []
            for barc in barcodes:
                logging.info("Processing {}".format(barc))
                settings["path"] = path.join(args.outdir, args.prefix + barc + "_")
                dfbarc = datadf[datadf["barcode"] == barc]
                settings["title"] = barc
                plots.extend(
                    make_plots(dfbarc, settings)
                )
            settings["path"] = path.join(args.outdir, args.prefix)
        else:
            plots = make_plots(datadf, settings)
        make_report(plots, settings["path"], logfile, statsfile)
        logging.info("Finished!")
    except Exception as e:
        logging.error(e, exc_info=True)
        print("\n\n\nIf you read this then NanoPlot has crashed :-(")
        print("Please report this issue at https://github.com/wdecoster/NanoPlot/issues")
        print("If you include the log file that would be really helpful.")
        print("Thanks!\n\n\n")
        raise


def get_args():
    epilog = """EXAMPLES:
    Nanoplot --summary sequencing_summary.txt --loglength -o summary-plots-log-transformed
    NanoPlot -t 2 --fastq reads1.fastq.gz reads2.fastq.gz --maxlength 40000 --plots hex dot
    NanoPlot --color yellow --bam alignment1.bam alignment2.bam alignment3.bam --downsample 10000
    """
    parser = ArgumentParser(
        description="Creates various plots for Oxford Nanopore sequencing data.".upper(),
        epilog=epilog,
        formatter_class=utils.custom_formatter,
        add_help=False)
    general = parser.add_argument_group(
        title='General options')
    general.add_argument("-h", "--help",
                         action="help",
                         help="show the help and exit")
    general.add_argument("-v", "--version",
                         help="Print version and exit.",
                         action="version",
                         version='NanoPlot {}'.format(__version__))
    general.add_argument("-t", "--threads",
                         help="Set the allowed number of threads to be used by the script",
                         default=4,
                         type=int)
    general.add_argument("--verbose",
                         help="Write log messages also to terminal.",
                         action="store_true")
    general.add_argument("--store",
                         help="Store the extracted data in a pickle file for future plotting.",
                         action="store_true")
    general.add_argument("--raw",
                         help="Store the extracted data in tab separated file.",
                         action="store_true")
    general.add_argument("-o", "--outdir",
                         help="Specify directory in which output has to be created.",
                         default=".")
    general.add_argument("-p", "--prefix",
                         help="Specify an optional prefix to be used for the output files.",
                         default="",
                         type=str)
    filtering = parser.add_argument_group(
        title='Options for filtering or transforming input prior to plotting')
    filtering.add_argument("--maxlength",
                           help="Drop reads longer than length specified.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--drop_outliers",
                           help="Drop outlier reads with extreme long length.",
                           action="store_true")
    filtering.add_argument("--downsample",
                           help="Reduce dataset to N reads by random sampling.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--loglength",
                           help="Logarithmic scaling of lengths in plots.",
                           action="store_true")
    filtering.add_argument("--alength",
                           help="Use aligned read lengths rather than sequenced length (bam mode)",
                           action="store_true")
    filtering.add_argument("--minqual",
                           help="Drop reads with an average quality lower than specified.",
                           type=int,
                           metavar='N')
    filtering.add_argument("--readtype",
                           help="Which read type to extract information about from summary. \
                                 Options are 1D, 2D, 1D2",
                           default="1D",
                           choices=['1D', '2D', '1D2'])
    filtering.add_argument("--barcoded",
                           help="Use if you want to split the summary file by barcode",
                           action="store_true")
    visual = parser.add_argument_group(
        title='Options for customizing the plots created')
    visual.add_argument("-c", "--color",
                        help="Specify a color for the plots, must be a valid matplotlib color",
                        default="#4CB391")
    visual.add_argument("-f", "--format",
                        help="Specify the output format of the plots.",
                        default="png",
                        type=str,
                        choices=['eps', 'jpeg', 'jpg', 'pdf', 'pgf', 'png', 'ps',
                                 'raw', 'rgba', 'svg', 'svgz', 'tif', 'tiff'])
    visual.add_argument("--plots",
                        help="Specify which bivariate plots have to be made.",
                        default=['kde', 'hex', 'dot'],
                        type=str,
                        nargs='*',
                        choices=['kde', 'hex', 'dot', 'pauvre'])
    visual.add_argument("--listcolors",
                        help="List the colors which are available for plotting and exit.",
                        action=utils.Action_Print_Colors,
                        default=False)
    visual.add_argument("--no-N50",
                        help="Hide the N50 mark in the read length histogram",
                        action="store_true")
    visual.add_argument("--title",
                        help="Add a title to all plots, requires quoting if using spaces",
                        type=str,
                        default=None)
    target = parser.add_argument_group(
        title="Input data sources, one of these is required.")
    mtarget = target.add_mutually_exclusive_group(
        required=True)
    mtarget.add_argument("--fastq",
                         help="Data is in one or more default fastq file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--fastq_rich",
                         help="Data is in one or more fastq file(s) generated by albacore or MinKNOW \
                             with additional information concerning channel and time.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--fastq_minimal",
                         help="Data is in one or more fastq file(s) generated by albacore or MinKNOW \
                             with additional information concerning channel and time. \
                             Minimal data is extracted swiftly without elaborate checks.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--summary",
                         help="Data is in one or more summary file(s) generated by albacore.",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--bam",
                         help="Data is in one or more sorted bam file(s).",
                         nargs='+',
                         metavar="file")
    mtarget.add_argument("--pickle",
                         help="Data is a pickle file stored earlier.",
                         metavar="pickle")
    args = parser.parse_args()
    if args.listcolors:
        utils.list_colors()
    return args


def filter_data(datadf, settings):
    '''
    Perform filtering on the data based on arguments set on commandline
    - use aligned length or sequenced length (bam mode only)
    - drop outliers
    - drop reads longer than args.maxlength
    - use log10 scaled reads
    - downsample reads to args.downsample
    Return an accurate prefix which is added to plotnames using this filtered data
    '''
    length_prefix_list = list()
    if settings["alength"] and settings["bam"]:
        settings["lengths_pointer"] = "aligned_lengths"
        length_prefix_list.append("Aligned_")
        logging.info("Using aligned read lengths for plotting.")
    else:
        settings["lengths_pointer"] = "lengths"
        logging.info("Using sequenced read lengths for plotting.")
    if settings["drop_outliers"]:
        num_reads_prior = len(datadf)
        datadf = nanomath.remove_length_outliers(datadf, settings["lengths_pointer"])
        length_prefix_list.append("OutliersRemoved_")
        num_reads_post = len(datadf)
        logging.info("Removing {} length outliers for plotting.".format(
            str(num_reads_prior - num_reads_post)))
    if settings["maxlength"]:
        num_reads_prior = len(datadf)
        datadf = datadf[datadf[settings["lengths_pointer"]] < settings["maxlength"]]
        length_prefix_list.append("MaxLength-" + str(settings["maxlength"]) + '_')
        num_reads_post = len(datadf)
        logging.info("Removing {} reads longer than {}bp.".format(
            str(num_reads_prior - num_reads_post),
            str(settings["maxlength"])))
    if settings["minqual"]:
        num_reads_prior = len(datadf)
        datadf = datadf[datadf["quals"] > settings["minqual"]]
        num_reads_post = len(datadf)
        logging.info("Removing {} reads with quality below Q{}.".format(
            str(num_reads_prior - num_reads_post),
            str(settings["minqual"])))
    if settings["loglength"]:
        datadf["log_" + settings["lengths_pointer"]] = np.log10(datadf[settings["lengths_pointer"]])
        settings["lengths_pointer"] = "log_" + settings["lengths_pointer"]
        length_prefix_list.append("Log_")
        logging.info("Using Log10 scaled read lengths.")
        settings["logBool"] = True
    else:
        settings["logBool"] = False
    if settings["downsample"]:
        new_size = min(settings["downsample"], len(datadf.index))
        length_prefix_list.append("Downsampled_")
        logging.info("Downsampling the dataset from {} to {} reads".format(
            len(datadf.index), new_size))
        datadf = datadf.sample(new_size)
    logging.info("Processed the reads, optionally filtered. {} reads left".format(str(len(datadf))))
    settings["length_prefix"] = ''.join(length_prefix_list)
    return(datadf, settings)


def make_plots(datadf, settings):
    '''
    Call plotting functions from nanoplotter
    settings["lengths_pointer"] is a column in the DataFrame specifying which lengths to use
    '''
    color = nanoplotter.check_valid_color(settings["color"])
    plotdict = {type: settings["plots"].count(type) for type in ["kde", "hex", "dot", 'pauvre']}
    plots = []
    if settings["no_N50"]:
        n50 = None
    else:
        n50 = nanomath.get_N50(np.sort(datadf["lengths"]))
    plots.extend(
        nanoplotter.length_plots(
            array=datadf["lengths"],
            name="Read length",
            path=settings["path"],
            n50=n50,
            color=color,
            figformat=settings["format"],
            title=settings["title"])
    )
    logging.info("Created length plots")
    if "quals" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf[settings["lengths_pointer"]],
                y=datadf["quals"],
                names=['Read lengths', 'Average read quality'],
                path=settings["path"] + settings["length_prefix"] + "LengthvsQualityScatterPlot",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                log=settings["logBool"],
                title=settings["title"])
        )
        logging.info("Created LengthvsQual plot")
    if "channelIDs" in datadf:
        plots.extend(
            nanoplotter.spatial_heatmap(
                array=datadf["channelIDs"],
                title=settings["title"],
                path=settings["path"] + "ActivityMap_ReadsPerChannel",
                color="Greens",
                figformat=settings["format"])
        )
        logging.info("Created spatialheatmap for succesfull basecalls.")
    if "start_time" in datadf:
        plots.extend(
            nanoplotter.time_plots(
                df=datadf,
                path=settings["path"],
                color=color,
                figformat=settings["format"],
                title=settings["title"])
        )
        logging.info("Created timeplots.")
    if "aligned_lengths" in datadf and "lengths" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf["aligned_lengths"],
                y=datadf["lengths"],
                names=["Aligned read lengths", "Sequenced read length"],
                path=settings["path"] + "AlignedReadlengthvsSequencedReadLength",
                figformat=settings["format"],
                plots=plotdict,
                color=color,
                title=settings["title"])
        )
        logging.info("Created AlignedLength vs Length plot.")
    if "maqpQ" in datadf:
        plots.extend(
            nanoplotter.scatter(
                x=datadf["mapQ"],
                y=datadf["quals"],
                names=["Read mapping quality", "Average basecall quality"],
                path=settings["path"] + "MappingQualityvsAverageBaseQuality",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                title=settings["title"])
        )
        logging.info("Created MapQvsBaseQ plot.")
        plots.extend(
            nanoplotter.scatter(
                x=datadf[settings["lengths_pointer"]],
                y=datadf["mapQ"],
                names=["Read length", "Read mapping quality"],
                path=settings["path"] + settings["length_prefix"] + "MappingQualityvsReadLength",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                log=settings["logBool"],
                title=settings["title"])
        )
        logging.info("Created Mapping quality vs read length plot.")
    if "percentIdentity" in datadf:
        minPID = np.percentile(datadf["percentIdentity"], 1)
        plots.extend(
            nanoplotter.scatter(
                x=datadf["percentIdentity"],
                y=datadf["aligned_quals"],
                names=["Percent identity", "Read quality"],
                path=settings["path"] + "PercentIdentityvsAverageBaseQuality",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                stat=stats.pearsonr,
                minvalx=minPID,
                title=settings["title"])
        )
        logging.info("Created Percent ID vs Base quality plot.")
        plots.extend(
            nanoplotter.scatter(
                x=datadf[settings["lengths_pointer"]],
                y=datadf["percentIdentity"],
                names=["Aligned read length", "Percent identity"],
                path=settings["path"] + "PercentIdentityvsAlignedReadLength",
                color=color,
                figformat=settings["format"],
                plots=plotdict,
                stat=stats.pearsonr,
                log=settings["logBool"],
                minvaly=minPID,
                title=settings["title"])
        )
        logging.info("Created Percent ID vs Length plot")
    return plots


def make_report(plots, path, logfile, statsfile):
    '''
    Creates a fat html report based on the previously created files
    plots is a list of Plot objects defined by a path and title
    statsfile is the file to which the stats have been saved,
    which is parsed to a table (rather dodgy)
    '''
    logging.info("Writing html report.")
    html_head = """<!DOCTYPE html>
    <html>
        <head>
        <meta charset="UTF-8">
            <style>
            table, th, td {
                text-align: left;
                padding: 2px;
                /* border: 1px solid black;
                border-collapse: collapse; */
            }
            h2 {
                line-height: 0pt;
            }
            </style>
            <title>NanoPlot Report</title>
        </head>"""
    html_content = ["\n<body>\n<h1>NanoPlot report</h1>"]
    html_content.append("<h2>Summary statistics</h2>")
    with open(statsfile) as stats:
        html_content.append('\n<table>')
        for line in stats:
            html_content.append('')
            linesplit = line.strip().split('\t')
            if line.startswith('Data'):
                html_content.append('\n<tr></tr>\n<tr>\n\t<td colspan="2">' +
                                    line.strip() + '</td>\n</tr>')
                break
            if len(linesplit) > 1:
                data = ''.join(["<td>" + e + "</td>" for e in linesplit])
                html_content.append("<tr>\n\t" + data + "\n</tr>")
            else:
                html_content.append('\n<tr></tr>\n<tr>\n\t<td colspan="2"><b>' +
                                    line.strip() + '</b></td>\n</tr>')
        for line in stats:
            html_content.append('\n<tr>\n\t<td colspan="2">' +
                                line.strip() + '</td>\n</tr>')
        html_content.append('</table>')
    html_content.append('\n<br>\n<br>\n<br>\n<br>')
    html_content.append("<h2>Plots</h2>")
    for plot in plots:
        html_content.append("\n<h3>" + plot.title + "</h3>\n" + plot.encode())
        html_content.append('\n<br>\n<br>\n<br>\n<br>')
    if logfile:
        html_content.append("<h2>Log file</h2>")
        with open(logfile) as logs:
            html_content.append('<pre>')
            for line in logs:
                html_content.append('\n'.join(wrap(line.rstrip(), width=150)))
            html_content.append('</pre>')
    html_body = '\n'.join(html_content) + "</body></html>"
    html_str = html_head + html_body
    with open(path + "NanoPlot-report.html", "w") as html_file:
        html_file.write(html_str)
    return path + "NanoPlot-report.html"


if __name__ == "__main__":
    main()
