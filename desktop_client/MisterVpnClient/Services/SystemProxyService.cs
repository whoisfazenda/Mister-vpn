using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace MisterVpnClient.Services;

public sealed class SystemProxyService
{
    private const string InternetSettingsPath = @"Software\Microsoft\Windows\CurrentVersion\Internet Settings";

    private object? _oldProxyEnable;
    private object? _oldProxyServer;
    private object? _oldProxyOverride;

    public void Enable()
    {
        using var key = Registry.CurrentUser.OpenSubKey(InternetSettingsPath, writable: true)
            ?? throw new InvalidOperationException("Не удалось открыть настройки прокси Windows.");

        _oldProxyEnable = key.GetValue("ProxyEnable");
        _oldProxyServer = key.GetValue("ProxyServer");
        _oldProxyOverride = key.GetValue("ProxyOverride");

        key.SetValue("ProxyEnable", 1, RegistryValueKind.DWord);
        key.SetValue("ProxyServer", "http=127.0.0.1:10808;https=127.0.0.1:10808", RegistryValueKind.String);
        key.SetValue("ProxyOverride", "<local>;127.*;localhost", RegistryValueKind.String);
        Refresh();
    }

    public void Restore()
    {
        using var key = Registry.CurrentUser.OpenSubKey(InternetSettingsPath, writable: true);
        if (key is null)
        {
            return;
        }

        RestoreValue(key, "ProxyEnable", _oldProxyEnable, RegistryValueKind.DWord);
        RestoreValue(key, "ProxyServer", _oldProxyServer, RegistryValueKind.String);
        RestoreValue(key, "ProxyOverride", _oldProxyOverride, RegistryValueKind.String);
        Refresh();
    }

    private static void RestoreValue(RegistryKey key, string name, object? value, RegistryValueKind kind)
    {
        if (value is null)
        {
            try { key.DeleteValue(name, throwOnMissingValue: false); } catch { }
            return;
        }

        key.SetValue(name, value, kind);
    }

    private static void Refresh()
    {
        InternetSetOption(IntPtr.Zero, 39, IntPtr.Zero, 0);
        InternetSetOption(IntPtr.Zero, 37, IntPtr.Zero, 0);
    }

    [DllImport("wininet.dll", SetLastError = true)]
    private static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
}
