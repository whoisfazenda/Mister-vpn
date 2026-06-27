namespace MisterVpnClient.Models;

public sealed record VlessProfile(
    string Id,
    string Host,
    int Port,
    string? Name,
    string Type,
    string Security,
    string? Flow,
    string? Sni,
    string? Fingerprint,
    string? PublicKey,
    string? ShortId,
    string? SpiderX,
    string? Path,
    string? HostHeader,
    string? ServiceName
);
