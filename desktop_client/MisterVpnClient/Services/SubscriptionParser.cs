using System.Net.Http;
using System.Text;
using MisterVpnClient.Models;

namespace MisterVpnClient.Services;

public sealed class SubscriptionParser
{
    private readonly HttpClient _httpClient = new()
    {
        Timeout = TimeSpan.FromSeconds(20)
    };

    public async Task<VlessProfile> ResolveAsync(string input, CancellationToken cancellationToken)
    {
        input = input.Trim();
        if (string.IsNullOrWhiteSpace(input))
        {
            throw new InvalidOperationException("Вставь ссылку подписки.");
        }

        if (input.StartsWith("vless://", StringComparison.OrdinalIgnoreCase))
        {
            return ParseVless(input);
        }

        if (!Uri.TryCreate(input, UriKind.Absolute, out var uri))
        {
            throw new InvalidOperationException("Ссылка должна быть vless:// или https://.");
        }

        var body = await _httpClient.GetStringAsync(uri, cancellationToken);
        var links = ExtractLinks(body);
        var vless = links.FirstOrDefault(x => x.StartsWith("vless://", StringComparison.OrdinalIgnoreCase));
        if (vless is null)
        {
            throw new InvalidOperationException("В подписке не найден VLESS-профиль.");
        }

        return ParseVless(vless);
    }

    private static IReadOnlyList<string> ExtractLinks(string body)
    {
        var links = new List<string>();
        foreach (var line in body.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (line.Contains("://", StringComparison.Ordinal))
            {
                links.Add(line);
            }
        }

        try
        {
            var bytes = Convert.FromBase64String(AddBase64Padding(body.Trim()));
            var decoded = Encoding.UTF8.GetString(bytes);
            foreach (var line in decoded.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                if (line.Contains("://", StringComparison.Ordinal))
                {
                    links.Add(line);
                }
            }
        }
        catch
        {
            // Plain text subscriptions are already handled above.
        }

        return links;
    }

    private static VlessProfile ParseVless(string link)
    {
        var uri = new Uri(link);
        var query = ParseQuery(uri.Query);
        var name = string.IsNullOrWhiteSpace(uri.Fragment) ? null : Uri.UnescapeDataString(uri.Fragment.TrimStart('#'));

        return new VlessProfile(
            Id: uri.UserInfo,
            Host: uri.Host,
            Port: uri.Port > 0 ? uri.Port : 443,
            Name: name,
            Type: Get(query, "type") ?? "tcp",
            Security: Get(query, "security") ?? "none",
            Flow: Get(query, "flow"),
            Sni: Get(query, "sni"),
            Fingerprint: Get(query, "fp"),
            PublicKey: Get(query, "pbk"),
            ShortId: Get(query, "sid"),
            SpiderX: Get(query, "spx"),
            Path: Get(query, "path"),
            HostHeader: Get(query, "host"),
            ServiceName: Get(query, "serviceName")
        );
    }

    private static Dictionary<string, string> ParseQuery(string query)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var part in query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var pair = part.Split('=', 2);
            var key = Uri.UnescapeDataString(pair[0]);
            var value = pair.Length > 1 ? Uri.UnescapeDataString(pair[1]) : "";
            result[key] = value;
        }

        return result;
    }

    private static string? Get(IReadOnlyDictionary<string, string> values, string key) =>
        values.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value) ? value : null;

    private static string AddBase64Padding(string value)
    {
        var mod = value.Length % 4;
        return mod == 0 ? value : value + new string('=', 4 - mod);
    }
}
