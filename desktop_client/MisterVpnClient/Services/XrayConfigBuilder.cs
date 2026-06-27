using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using MisterVpnClient.Models;

namespace MisterVpnClient.Services;

public sealed class XrayConfigBuilder
{
    public string Build(VlessProfile profile)
    {
        Directory.CreateDirectory(AppSettings.AppDir);
        var path = Path.Combine(AppSettings.AppDir, "xray.generated.json");

        var streamSettings = new JsonObject
        {
            ["network"] = profile.Type,
            ["security"] = profile.Security
        };

        if (profile.Security.Equals("reality", StringComparison.OrdinalIgnoreCase))
        {
            streamSettings["realitySettings"] = new JsonObject
            {
                ["serverName"] = profile.Sni ?? profile.Host,
                ["fingerprint"] = profile.Fingerprint ?? "chrome",
                ["publicKey"] = profile.PublicKey ?? "",
                ["shortId"] = profile.ShortId ?? "",
                ["spiderX"] = profile.SpiderX ?? "/"
            };
        }
        else if (profile.Security.Equals("tls", StringComparison.OrdinalIgnoreCase))
        {
            streamSettings["tlsSettings"] = new JsonObject
            {
                ["serverName"] = profile.Sni ?? profile.Host,
                ["fingerprint"] = profile.Fingerprint ?? "chrome"
            };
        }

        if (profile.Type.Equals("ws", StringComparison.OrdinalIgnoreCase))
        {
            var headers = new JsonObject();
            if (!string.IsNullOrWhiteSpace(profile.HostHeader))
            {
                headers["Host"] = profile.HostHeader;
            }

            streamSettings["wsSettings"] = new JsonObject
            {
                ["path"] = profile.Path ?? "/",
                ["headers"] = headers
            };
        }
        else if (profile.Type.Equals("grpc", StringComparison.OrdinalIgnoreCase))
        {
            streamSettings["grpcSettings"] = new JsonObject
            {
                ["serviceName"] = profile.ServiceName ?? ""
            };
        }

        var user = new JsonObject
        {
            ["id"] = profile.Id,
            ["encryption"] = "none"
        };
        if (!string.IsNullOrWhiteSpace(profile.Flow))
        {
            user["flow"] = profile.Flow;
        }

        var root = new JsonObject
        {
            ["log"] = new JsonObject
            {
                ["loglevel"] = "warning"
            },
            ["inbounds"] = new JsonArray
            {
                new JsonObject
                {
                    ["tag"] = "http-in",
                    ["listen"] = "127.0.0.1",
                    ["port"] = 10808,
                    ["protocol"] = "http"
                },
                new JsonObject
                {
                    ["tag"] = "socks-in",
                    ["listen"] = "127.0.0.1",
                    ["port"] = 10809,
                    ["protocol"] = "socks",
                    ["settings"] = new JsonObject
                    {
                        ["udp"] = true
                    }
                }
            },
            ["outbounds"] = new JsonArray
            {
                new JsonObject
                {
                    ["tag"] = "proxy",
                    ["protocol"] = "vless",
                    ["settings"] = new JsonObject
                    {
                        ["vnext"] = new JsonArray
                        {
                            new JsonObject
                            {
                                ["address"] = profile.Host,
                                ["port"] = profile.Port,
                                ["users"] = new JsonArray { user }
                            }
                        }
                    },
                    ["streamSettings"] = streamSettings
                },
                new JsonObject
                {
                    ["tag"] = "direct",
                    ["protocol"] = "freedom"
                }
            }
        };

        File.WriteAllText(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        return path;
    }
}
