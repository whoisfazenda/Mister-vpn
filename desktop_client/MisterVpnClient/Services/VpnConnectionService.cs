using System.Diagnostics;
using System.IO;
using MisterVpnClient.Models;

namespace MisterVpnClient.Services;

public sealed class VpnConnectionService
{
    private readonly SubscriptionParser _parser = new();
    private readonly XrayConfigBuilder _configBuilder = new();
    private readonly SystemProxyService _proxyService = new();
    private Process? _xrayProcess;

    public bool IsConnected => _xrayProcess is { HasExited: false };

    public async Task ConnectAsync(string subscription, bool enableSystemProxy, Action<string> log, CancellationToken cancellationToken)
    {
        if (IsConnected)
        {
            log("Уже подключено.");
            return;
        }

        var xrayPath = FindXray();
        if (xrayPath is null)
        {
            throw new FileNotFoundException("Не найден xray.exe. Положи его в desktop_client\\MisterVpnClient\\modules\\xray\\xray.exe.");
        }

        log("Читаю подписку...");
        VlessProfile profile = await _parser.ResolveAsync(subscription, cancellationToken);
        log($"Профиль: {profile.Name ?? profile.Host}");

        var configPath = _configBuilder.Build(profile);
        log("Конфиг Xray создан.");

        var startInfo = new ProcessStartInfo
        {
            FileName = xrayPath,
            Arguments = $"-config \"{configPath}\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = Path.GetDirectoryName(xrayPath) ?? AppContext.BaseDirectory
        };

        _xrayProcess = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        _xrayProcess.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log(e.Data); };
        _xrayProcess.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log(e.Data); };

        if (!_xrayProcess.Start())
        {
            throw new InvalidOperationException("Не удалось запустить Xray.");
        }

        _xrayProcess.BeginOutputReadLine();
        _xrayProcess.BeginErrorReadLine();
        await Task.Delay(900, cancellationToken);

        if (_xrayProcess.HasExited)
        {
            throw new InvalidOperationException("Xray завершился сразу после запуска. Проверь ссылку подписки.");
        }

        if (enableSystemProxy)
        {
            _proxyService.Enable();
            log("Системный прокси Windows включен.");
        }

        log("Подключено.");
    }

    public void Disconnect(Action<string> log)
    {
        try
        {
            _proxyService.Restore();
            log("Системный прокси восстановлен.");
        }
        catch (Exception ex)
        {
            log($"Не удалось восстановить прокси: {ex.Message}");
        }

        try
        {
            if (_xrayProcess is { HasExited: false })
            {
                _xrayProcess.Kill(entireProcessTree: true);
                _xrayProcess.WaitForExit(2500);
            }

            log("Отключено.");
        }
        finally
        {
            _xrayProcess?.Dispose();
            _xrayProcess = null;
        }
    }

    private static string? FindXray()
    {
        var local = Path.Combine(AppContext.BaseDirectory, "modules", "xray", "xray.exe");
        if (File.Exists(local))
        {
            return local;
        }

        var projectLocal = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "modules", "xray", "xray.exe"));
        if (File.Exists(projectLocal))
        {
            return projectLocal;
        }

        var deveil = @"D:\DeVeil\modules\xray\xray.exe";
        return File.Exists(deveil) ? deveil : null;
    }
}
