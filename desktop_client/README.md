# Mister VPN Windows Client

Минимальный Windows-клиент в стиле Mister VPN.

## Что умеет

- принимает `vless://` или HTTPS-ссылку подписки;
- достает первый VLESS-профиль из подписки;
- генерирует Xray config;
- запускает локальный HTTP proxy `127.0.0.1:10808` и SOCKS `127.0.0.1:10809`;
- по желанию включает системный прокси Windows;
- сохраняет ссылку локально в `%LOCALAPPDATA%\MisterVpnClient\settings.json`.

## Xray

Приложение ищет `xray.exe` в таком порядке:

1. рядом с exe: `modules\xray\xray.exe`;
2. в проекте: `desktop_client\MisterVpnClient\modules\xray\xray.exe`;
3. временно, для теста: `D:\DeVeil\modules\xray\xray.exe`.

Для релиза положи свой `xray.exe` в `modules\xray`.

## Сборка

```powershell
$env:DOTNET_CLI_HOME = "$PWD\.dotnet-home"
.\.dotnet\dotnet.exe build .\desktop_client\MisterVpnClient\MisterVpnClient.csproj --configfile .\desktop_client\MisterVpnClient\NuGet.Config
```
