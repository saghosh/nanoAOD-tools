#!/usr/bin/env python
import os
import time
import ROOT
ROOT.PyConfig.IgnoreCommandLineOptions = True
from PhysicsTools.NanoAODTools.postprocessing.framework.branchselection import BranchSelection
from PhysicsTools.NanoAODTools.postprocessing.framework.datamodel import InputTree
from PhysicsTools.NanoAODTools.postprocessing.framework.eventloop import eventLoop
from PhysicsTools.NanoAODTools.postprocessing.framework.output import FriendOutput, FullOutput
from PhysicsTools.NanoAODTools.postprocessing.framework.preskimming import preSkim
from PhysicsTools.NanoAODTools.postprocessing.framework.jobreport import JobReport

class PostProcessor :
    def __init__(self,outputDir,inputFiles,cut=None,branchsel=None,modules=[],compression="LZMA:9",friend=False,postfix=None,
		 jsonInput=None,noOut=False,justcount=False,provenance=False,haddFileName=None,fwkJobReport=False,histFileName=None,histDirName=None, outputbranchsel=None,maxEntries=None):
	self.outputDir=outputDir
	self.inputFiles=inputFiles
	self.cut=cut
	self.modules=modules
	self.compression=compression
	self.postfix=postfix
	self.json=jsonInput
	self.noOut=noOut
	self.friend=friend
	self.justcount=justcount
	self.provenance=provenance
	self.jobReport = JobReport() if fwkJobReport else None
	self.haddFileName=haddFileName
	self.histFile = None
	self.histDirName = None
	if self.jobReport and not self.haddFileName :
		print "Because you requested a FJR we assume you want the final hadd. No name specified for the output file, will use tree.root"
		self.haddFileName="tree.root"
 	self.branchsel = BranchSelection(branchsel) if branchsel else None 
        self.outputbranchsel = BranchSelection(outputbranchsel) if outputbranchsel else None
        self.histFileName=histFileName
        self.histDirName=histDirName
        self.maxEntries = maxEntries if maxEntries else 9223372036854775807L # 2^63 - 1, largest int64
    def run(self) :
        outpostfix = self.postfix if self.postfix != None else ("_Friend" if self.friend else "_Skim")
    	if not self.noOut:
            
            if self.compression != "none":
                ROOT.gInterpreter.ProcessLine("#include <Compression.h>")
                (algo, level) = self.compression.split(":")
                compressionLevel = int(level)
                if   algo == "LZMA": compressionAlgo  = ROOT.ROOT.kLZMA
                elif algo == "ZLIB": compressionAlgo  = ROOT.ROOT.kZLIB
                elif algo == "LZ4":  compressionAlgo  = ROOT.ROOT.kLZ4
                else: raise RuntimeError("Unsupported compression %s" % algo)
            else:
                compressionLevel = 0 
	    print "Will write selected trees to "+self.outputDir
            if not self.justcount:
                if not os.path.exists(self.outputDir):
                    os.system("mkdir -p "+self.outputDir)
        else:
            compressionLevel = 0

	if self.noOut:
	    if len(self.modules) == 0: 
		raise RuntimeError("Running with --noout and no modules does nothing!")

        # Open histogram file, if desired 
        if (self.histFileName != None and self.histDirName == None) or (self.histFileName == None and self.histDirName != None) :
            raise RuntimeError("Must specify both histogram file and histogram directory!")
        elif self.histFileName != None and self.histDirName != None:
            self.histFile = ROOT.TFile.Open( self.histFileName, "RECREATE" )
        else :
            self.histFile = None

    
        for m in self.modules:
            if hasattr( m, 'writeHistFile') and m.writeHistFile :
                m.beginJob(histFile=self.histFile,histDirName=self.histDirName)
            else :
                m.beginJob()

	fullClone = (len(self.modules) == 0)
	outFileNames=[]
        t0 = time.clock()
	totEntriesRead=0
	for fname in self.inputFiles:
	    ffnames = []
	    if "," in fname:
	        fnames = fname.split(',')
	        fname, ffnames = fnames[0], fnames[1:]

	    # open input file
	    inFile = ROOT.TFile.Open(fname)

	    #get input tree
	    inTree = inFile.Get("Events")
	    if inTree == None: inTree = inFile.Get("Friends")
	    nEntries = min(inTree.GetEntries(), self.maxEntries)
	    totEntriesRead+=nEntries
	    # pre-skimming
	    elist,jsonFilter = preSkim(inTree, self.json, self.cut, maxEntries = self.maxEntries)
	    if self.justcount:
		print 'Would select %d entries from %s'%(elist.GetN() if elist else nEntries, fname)
		continue
	    else:
		print 'Pre-select %d entries out of %s '%(elist.GetN() if elist else nEntries,nEntries)
		inAddFiles = []
		inAddTrees = []
	    for ffname in ffnames:
		inAddFiles.append(ROOT.TFile.Open(ffname))
		inAddTree = inAddFiles[-1].Get("Events")
		if inAddTree == None: inAddTree = inAddFiles[-1].Get("Friends")
		inAddTrees.append(inAddTree)
		inTree.AddFriend(inAddTree)

	    if fullClone:
		# no need of a reader (no event loop), but set up the elist if available
		if elist: inTree.SetEntryList(elist)
	    else:
		# initialize reader
		inTree = InputTree(inTree, elist) 

	    # prepare output file
            if not self.noOut:
                outFileName = os.path.join(self.outputDir, os.path.basename(fname).replace(".root",outpostfix+".root"))
                outFile = ROOT.TFile.Open(outFileName, "RECREATE", "", compressionLevel)
                outFileNames.append(outFileName)
                if compressionLevel: 
                    outFile.SetCompressionAlgorithm(compressionAlgo)
                # prepare output tree
                if self.friend:
                    outTree = FriendOutput(inFile, inTree, outFile)
                else:
                    outTree = FullOutput(
                        inFile,
                        inTree,
                        outFile,
                        branchSelection=self.branchsel,
                        outputbranchSelection=self.outputbranchsel,
                        fullClone=fullClone, maxEntries = self.maxEntries,
                        jsonFilter=jsonFilter,
                        provenance=self.provenance)
            else : 
                outFile = None
                outTree = None

	    # process events, if needed
	    if not fullClone:
		(nall, npass, timeLoop) = eventLoop(self.modules, inFile, outFile, inTree, outTree, maxEvents = self.maxEntries)
		print 'Processed %d preselected entries from %s (%s entries). Finally selected %d entries' % (nall, fname, nEntries, npass)
	    else:
                nall = nEntries
		print 'Selected %d entries from %s' % (outTree.tree().GetEntries(), fname)

	    # now write the output
            if not self.noOut: 
                outTree.write()
                outFile.Close()
                print "Done %s" % outFileName
	    if self.jobReport:
		self.jobReport.addInputFile(fname,nall)
		
	for m in self.modules: m.endJob()
	
	print  totEntriesRead/(time.clock()-t0), "Hz"


	if self.haddFileName :
		haddnano = "./haddnano.py" if os.path.isfile("./haddnano.py") else "haddnano.py"
		os.system("%s %s %s" %(haddnano, self.haddFileName," ".join(outFileNames)))
	if self.jobReport :
		self.jobReport.addOutputFile(self.haddFileName)
		self.jobReport.save()
