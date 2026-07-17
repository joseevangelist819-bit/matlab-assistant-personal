using System;
using System.Diagnostics;
using System.IO;

internal static class MatlabAgentLauncher
{
    public static int Main(string[] args)
    {
        string home = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string python = Path.Combine(home, "runtime", "python.exe");
        if (!File.Exists(python))
        {
            Console.Error.WriteLine("{\"error\":\"RuntimeMissing\",\"message\":\"Bundled Python runtime is missing.\"}");
            return 3;
        }
        var info = new ProcessStartInfo(python);
        info.UseShellExecute = false;
        info.WorkingDirectory = home;
        info.EnvironmentVariables["MATLAB_AGENT_HOME"] = home;
        info.EnvironmentVariables["PYTHONPATH"] = home;
        info.Arguments = "-m workflow_engine.matlab_agent_cli " + JoinArguments(args);
        using (Process process = Process.Start(info))
        {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    private static string JoinArguments(string[] args)
    {
        string[] escaped = new string[args.Length];
        for (int i = 0; i < args.Length; i++) escaped[i] = Quote(args[i]);
        return string.Join(" ", escaped);
    }

    private static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] {' ', '\t', '"'}) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
