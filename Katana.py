import re
import os

from System import *
from System.Diagnostics import *
from System.IO import *
from System.Text.RegularExpressions import *

from Deadline.Plugins import *
from Deadline.Scripting import *

######################################################################
## This is the function that Deadline calls to get an instance of the
## main DeadlinePlugin class.
######################################################################
def GetDeadlinePlugin():
    return KatanaPlugin()

def CleanupDeadlinePlugin( deadlinePlugin ):
    deadlinePlugin.Cleanup()

######################################################################
## This is the main DeadlinePlugin class for the Katana plugin.
######################################################################
class KatanaPlugin( DeadlinePlugin ):

    def __init__( self ):
        self.InitializeProcessCallback += self.InitializeProcess
        self.RenderExecutableCallback += self.RenderExecutable
        self.RenderArgumentCallback += self.RenderArgument
        self.StartupDirectoryCallback += self.StartupDirectory
        self.PreRenderTasksCallback += self.PreRenderTasks
        self.PostRenderTasksCallback += self.PostRenderTasks

        self.Version = 3
        self.KatanaExecutable = ""

    def Cleanup( self ):
        for stdoutHandler in self.StdoutHandlers:
            del stdoutHandler.HandleCallback

        del self.InitializeProcessCallback
        del self.RenderExecutableCallback
        del self.RenderArgumentCallback
        del self.StartupDirectoryCallback
        del self.PreRenderTasksCallback
        del self.PostRenderTasksCallback

    ## Called by Deadline to initialize the process.
    def InitializeProcess( self ):
        self.PluginType = PluginType.Simple
        self.StdoutHandling = True
        self.UseProcessTree = False
        
        self.FinishedFrameCount = 0

        # Initial Arnold values
        self.ArnoldPassStart = "1"
        self.ArnoldPassEnd = "1"
        self.ArnoldProgress = "0"
        self.ArnoldProgressText = ""

        # Katana stdout handlers
        self.AddStdoutHandlerCallback( ".*Starting frame ([0-9]+).*" ).HandleCallback += self.HandleKatanaFrameProgress # Starting frame 3 ...
        self.AddStdoutHandlerCallback( ".*Frame ([0-9]+) completed.*" ).HandleCallback += self.HandleKatanaFrameProgress # Frame 2 completed
        self.AddStdoutHandlerCallback( ".*ERROR +\\|.*" ).HandleCallback += self.HandleStdoutError

        # Arnold stdout handlers
        self.AddStdoutHandlerCallback( ".*[kat] Starting render pass ([0-9]+) of ([0-9]+).*" ).HandleCallback += self.HandleArnoldRenderProgress # [kat] Starting render pass 1 of 1
        self.AddStdoutHandlerCallback( "([0-9]+)(% done.*)" ).HandleCallback += self.HandleArnoldRenderProgress # 15% done - 2 rays/pixel
        self.AddStdoutHandlerCallback( ".*[kat] Finished render pass ([0-9]+) of ([0-9]+).*" ).HandleCallback += self.HandleArnoldRenderProgress # [kat] Finished render pass 1 of 1
        
        #Redshift stdout handlers
        self.AddStdoutHandlerCallback( "Block (\\d+)/(\\d+) .+ rendered" ).HandleCallback += self.HandleRedshiftBlockRendered
        
    ## Called by Deadline to get the render executable.
    def RenderExecutable( self ):
        versionString = self.GetPluginInfoEntryWithDefault( "Version", "3" )
        self.Version = int(versionString)

        self.LogInfo( "Rendering with Katana version: %s" % versionString )

        renderExeList = self.GetConfigEntry( "Katana_Executable" + versionString )
        self.KatanaExecutable = FileUtils.SearchFileList( renderExeList )
        if( self.KatanaExecutable == "" ):
            self.FailRender( "Katana render executable was not found in the semicolon separated list \"" + renderExeList + "\". The path to the render executable can be configured from the Plugin Configuration in the Deadline Monitor." )
        else:
            self.LogInfo( self.KatanaExecutable )

        return self.KatanaExecutable
        
    ## Called by Deadline to get the render arguments.
    def RenderArgument( self ):
        arguments = "--batch "

        katanaFile = RepositoryUtils.CheckPathMapping( self.GetPluginInfoEntryWithDefault( "KatanaFile", self.GetDataFilename() ) )
        arguments += "--katana-file=\"%s\" " % katanaFile

        frameList = str(self.GetStartFrame()) + "-" + str(self.GetEndFrame())
        arguments += "-t %s " % frameList

        renderNode = self.GetPluginInfoEntryWithDefault( "RenderNode", "" ) 
        if len(renderNode): # The user has selected a render node
            arguments += "--render-node=%s " % renderNode
        
        gpuOverrides = self.GetGpuOverrides()
        gpuString = "".join( [ "1" if str( index ) in gpuOverrides else "0" for index in range(16) ] )

        self.SetProcessEnvironmentVariable( "REDSHIFT_SELECTED_CUDA_DEVICES", gpuString )
        
        return arguments

    ## Called by Deadline to return the current working directory (CWD).
    def StartupDirectory( self ):
        workingDirectory = self.GetPluginInfoEntryWithDefault( "WorkingDirectory", "" ).strip()
        if workingDirectory != "":
            workingDirectory = RepositoryUtils.CheckPathMapping( workingDirectory )
            if SystemUtils.IsRunningOnWindows():
                workingDirectory = workingDirectory.replace( "/", "\\" )
            else:
                workingDirectory = workingDirectory.replace( "\\", "/" )
        else:
            workingDirectory = os.path.dirname( self.KatanaExecutable )

        return workingDirectory

    ## Called by Deadline before the render begins.
    def PreRenderTasks( self ):
        self.SetStatusMessage( "Running Katana Job..." )

    ## Called by Deadline after the render finishes.
    def PostRenderTasks( self ):
        self.SetStatusMessage( "Katana Job Completed" )

    # Update Katana Progress.
    def HandleKatanaFrameProgress( self ):
        if re.search( "completed", self.GetRegexMatch( 0 ) ):
            currentFrame = int(self.GetRegexMatch(1))
            self.FinishedFrameCount = ( currentFrame - self.GetStartFrame() )
            newProgress = ( float( (currentFrame - self.GetStartFrame())+1 ) / ((self.GetEndFrame() - self.GetStartFrame())+1)) * 100
            self.SetProgress( newProgress )

        msg = self.GetRegexMatch(0).split()
        if len(msg) > 2:
            msg = " ".join(msg[2:])
            self.SetStatusMessage( msg )

    def HandleStdoutError( self ):
        self.FailRender( self.GetRegexMatch( 0 ) )

    # Update Arnold Progress.
    def HandleArnoldRenderProgress( self ):
        if re.search( "Starting render pass ", self.GetRegexMatch( 0 ) ):
            self.ArnoldPassStart = self.GetRegexMatch( 1 )
            self.ArnoldPassEnd = self.GetRegexMatch( 2 )
            msg = "Arnold: Starting Render Pass " + str(self.ArnoldPassStart) + " of " + str(self.ArnoldPassEnd)
            self.SetStatusMessage( msg )
        
        elif re.search( " done", self.GetRegexMatch( 0 ) ):
            self.ArnoldProgress = self.GetRegexMatch( 1 )
            self.ArnoldProgressText = self.GetRegexMatch( 2 )
            msg = "Arnold: Rendering Pass " + str(self.ArnoldPassStart) + " of " + str(self.ArnoldPassEnd) + " : " + str(self.ArnoldProgress) + str(self.ArnoldProgressText)
            self.SetStatusMessage( msg )

            startFrame = self.GetStartFrame()
            endFrame = self.GetEndFrame()
            
            # Update Task progress if rendering 1 frame per task.
            if endFrame - startFrame == 0:
                self.SetProgress(float(self.ArnoldProgress))

        elif re.search( "Finished render pass ", self.GetRegexMatch( 0 ) ):
            msg = "Arnold: Finished Rendering Pass " + str(self.ArnoldPassStart) + " of " + str(self.ArnoldPassEnd)
            self.SetStatusMessage( msg )
        else:
            pass
    
    def HandleRedshiftBlockRendered( self ):
        startFrame = self.GetStartFrame()
        endFrame = self.GetEndFrame()
     
        completedBlockNumber = float( self.GetRegexMatch( 1 ) )
        totalBlockCount = float( self.GetRegexMatch( 2 ) )
        finishedFrames = completedBlockNumber / totalBlockCount
        finishedFrames = finishedFrames +self.FinishedFrameCount
        
        if( endFrame - startFrame + 1 != 0 ):
            progress = 100 * ( finishedFrames / ( endFrame - startFrame + 1) )
            self.SetProgress( progress )
            
    def GetGpuOverrides( self ):
        resultGPUs = []
        
        # If the number of gpus per task is set, then need to calculate the gpus to use.
        gpusPerTask = self.GetIntegerPluginInfoEntryWithDefault( "GPUsPerTask", 0 )
        gpusSelectDevices = self.GetPluginInfoEntryWithDefault( "GPUsSelectDevices", "" )

        if self.OverrideGpuAffinity():
            overrideGPUs = self.GpuAffinity()
            if gpusPerTask == 0 and gpusSelectDevices != "":
                gpus = gpusSelectDevices.split( "," )
                notFoundGPUs = []
                for gpu in gpus:
                    if int( gpu ) in overrideGPUs:
                        resultGPUs.append( gpu )
                    else:
                        notFoundGPUs.append( gpu )
                
                if len( notFoundGPUs ) > 0:
                    self.LogWarning( "The Worker is overriding its GPU affinity and the following GPUs do not match the Workers affinity so they will not be used: " + ",".join( notFoundGPUs ) )
                if len( resultGPUs ) == 0:
                    self.FailRender( "The Worker does not have affinity for any of the GPUs specified in the job." )
            elif gpusPerTask > 0:
                if gpusPerTask > len( overrideGPUs ):
                    self.LogWarning( "The Worker is overriding its GPU affinity and the Worker only has affinity for " + str( len( overrideGPUs ) ) + " gpus of the " + str( gpusPerTask ) + " requested." )
                    resultGPUs = [ str( gpu ) for gpu in overrideGPUs ]
                else:
                    resultGPUs = [ str( gpu ) for gpu in overrideGPUs if gpu < gpusPerTask ]
            else:
                resultGPUs = [ str( gpu ) for gpu in overrideGPUs ]
        elif gpusPerTask == 0 and gpusSelectDevices != "":
            resultGPUs = gpusSelectDevices.split( "," )

        elif gpusPerTask > 0:
            gpuList = []
            for i in range( ( self.GetThreadNumber() * gpusPerTask ), ( self.GetThreadNumber() * gpusPerTask ) + gpusPerTask ):
                gpuList.append( str( i ) )
            resultGPUs = gpuList
        
        resultGPUs = list( resultGPUs )
        
        return resultGPUs