using System.Reflection;

internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        if (args.Length < 4)
        {
            Console.Error.WriteLine("Usage: RconCli.exe <ip> <port> <password> <command>");
            return 2;
        }

        var ip = args[0];
        if (!int.TryParse(args[1], out var port))
        {
            Console.Error.WriteLine("Invalid port.");
            return 2;
        }

        var password = args[2];
        var rawCommand = string.Join(" ", args.Skip(3)).Trim();
        if (string.IsNullOrWhiteSpace(rawCommand))
        {
            Console.Error.WriteLine("Command cannot be empty.");
            return 2;
        }

        try
        {
            var clientAssembly = ResolveAssembly("TheIsleEvrimaRconClient");
            var extensionAssembly = ResolveAssembly("TheIsleEvrimaRconClient.Extensions");

            var clientType = RequireType(clientAssembly, "TheIsleEvrimaRconClient.EvrimaRconClient");
            var commandType = RequireType(clientAssembly, "TheIsleEvrimaRconClient.EvrimaRconCommand");
            var extensionsType = RequireType(extensionAssembly, "TheIsleEvrimaRconClient.Extensions.EvrimaRconClientExtensions");

            var client = CreateClient(clientType, ip, port, password);
            if (client is null)
            {
                Console.Error.WriteLine("Failed to construct EvrimaRconClient.");
                return 1;
            }

            await InvokeBestConnect(client, TimeSpan.FromSeconds(10));
            await InvokeBestAuthenticate(client, password, TimeSpan.FromSeconds(10));

            var (verb, argument) = ParseCommand(rawCommand);
            var response = await InvokeBestSend(
                client,
                clientType,
                commandType,
                extensionsType,
                verb,
                argument,
                rawCommand,
                TimeSpan.FromSeconds(10));

            Console.WriteLine(ToOutput(response));
            return 0;
        }
        catch (TimeoutException)
        {
            Console.Error.WriteLine("Timeout.");
            return 5;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static Assembly ResolveAssembly(string simpleName)
    {
        return AppDomain.CurrentDomain.GetAssemblies()
                   .FirstOrDefault(a => string.Equals(a.GetName().Name, simpleName, StringComparison.OrdinalIgnoreCase))
               ?? Assembly.Load(simpleName);
    }

    private static Type RequireType(Assembly assembly, string fullName)
    {
        return assembly.GetType(fullName, throwOnError: true, ignoreCase: false)
               ?? throw new InvalidOperationException($"Type not found: {fullName}");
    }

    private static object? CreateClient(Type clientType, string ip, int port, string password)
    {
        foreach (var ctor in clientType.GetConstructors(BindingFlags.Public | BindingFlags.Instance)
                     .OrderByDescending(c => c.GetParameters().Length))
        {
            if (!TryBuildCtorArgs(ctor.GetParameters(), ip, port, password, out var args))
            {
                continue;
            }

            try
            {
                return ctor.Invoke(args);
            }
            catch
            {
                // Try next constructor.
            }
        }

        return null;
    }

    private static bool TryBuildCtorArgs(ParameterInfo[] parameters, string ip, int port, string password, out object?[] args)
    {
        args = new object?[parameters.Length];

        for (var i = 0; i < parameters.Length; i++)
        {
            var p = parameters[i];
            var pt = p.ParameterType;
            var name = (p.Name ?? string.Empty).ToLowerInvariant();

            if (pt == typeof(string))
            {
                args[i] = (name.Contains("pass") || name.Contains("auth") || name.Contains("token")) ? password : ip;
                continue;
            }

            if (pt == typeof(int))
            {
                args[i] = port;
                continue;
            }

            if (pt == typeof(ushort))
            {
                args[i] = checked((ushort)port);
                continue;
            }

            if (pt == typeof(bool))
            {
                args[i] = false;
                continue;
            }

            if (p.HasDefaultValue)
            {
                args[i] = p.DefaultValue;
                continue;
            }

            if (!pt.IsValueType)
            {
                args[i] = null;
                continue;
            }

            return false;
        }

        return true;
    }

    private static (string Verb, string Argument) ParseCommand(string rawCommand)
    {
        var parts = rawCommand.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
        return (
            parts.Length > 0 ? parts[0].Trim() : string.Empty,
            parts.Length > 1 ? parts[1].Trim() : string.Empty
        );
    }

    private static async Task InvokeBestConnect(object client, TimeSpan timeout)
    {
        var method = client.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .FirstOrDefault(m =>
                m.GetParameters().Length == 0 &&
                (m.Name.Contains("Connect", StringComparison.OrdinalIgnoreCase) || m.Name.Equals("Open", StringComparison.OrdinalIgnoreCase)));

        if (method is not null)
        {
            await InvokeMethodAsync(client, method, Array.Empty<object?>(), timeout);
        }
    }

    private static async Task InvokeBestAuthenticate(object client, string password, TimeSpan timeout)
    {
        var method = client.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .FirstOrDefault(m =>
                m.GetParameters().Length == 1 &&
                m.GetParameters()[0].ParameterType == typeof(string) &&
                (m.Name.Contains("Auth", StringComparison.OrdinalIgnoreCase)
                 || m.Name.Contains("Authorize", StringComparison.OrdinalIgnoreCase)
                 || m.Name.Contains("Login", StringComparison.OrdinalIgnoreCase)
                 || m.Name.Contains("Password", StringComparison.OrdinalIgnoreCase)));

        if (method is not null)
        {
            await InvokeMethodAsync(client, method, new object?[] { password }, timeout);
        }
    }

    private static async Task<object?> InvokeBestSend(
        object client,
        Type clientType,
        Type commandType,
        Type extensionsType,
        string commandVerb,
        string commandArgument,
        string rawCommand,
        TimeSpan timeout)
    {
        if (string.Equals(commandVerb, "announce", StringComparison.OrdinalIgnoreCase))
        {
            var announceExtension = extensionsType.GetMethods(BindingFlags.Static | BindingFlags.Public)
                .Where(m => string.Equals(m.Name, "Announce", StringComparison.OrdinalIgnoreCase))
                .Where(m => m.GetParameters().Length >= 2 && m.GetParameters()[0].ParameterType.IsAssignableFrom(clientType))
                .OrderBy(m => m.GetParameters().Length)
                .FirstOrDefault();

            if (announceExtension is not null)
            {
                var ps = announceExtension.GetParameters();
                var args = new object?[ps.Length];
                args[0] = client;

                for (var i = 1; i < ps.Length; i++)
                {
                    var p = ps[i];
                    if (p.ParameterType == typeof(string))
                    {
                        args[i] = commandArgument;
                    }
                    else if (p.HasDefaultValue)
                    {
                        args[i] = p.DefaultValue;
                    }
                    else if (!p.ParameterType.IsValueType)
                    {
                        args[i] = null;
                    }
                    else
                    {
                        args = null;
                        break;
                    }
                }

                if (args is not null)
                {
                    return await InvokeMethodAsync(null, announceExtension, args, timeout);
                }
            }
        }

        var instanceCandidates = clientType.GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .Where(IsSendLike)
            .OrderByDescending(m => ScoreMethodName(m.Name, "SendCommand", "Send", "Execute", "Command"));

        foreach (var method in instanceCandidates)
        {
            if (!TryBuildInvocationArgs(method.GetParameters(), clientType, commandType, client, commandVerb, commandArgument, rawCommand, out var args))
            {
                continue;
            }

            try
            {
                return await InvokeMethodAsync(client, method, args, timeout);
            }
            catch
            {
                // Try next method.
            }
        }

        var extensionCandidates = extensionsType.GetMethods(BindingFlags.Static | BindingFlags.Public)
            .Where(IsSendLike)
            .Where(m => m.GetParameters().Length > 0 && m.GetParameters()[0].ParameterType.IsAssignableFrom(clientType))
            .OrderByDescending(m => ScoreMethodName(m.Name, "SendCommand", "Send", "Execute", "Command"));

        foreach (var method in extensionCandidates)
        {
            if (!TryBuildInvocationArgs(method.GetParameters(), clientType, commandType, client, commandVerb, commandArgument, rawCommand, out var args))
            {
                continue;
            }

            try
            {
                return await InvokeMethodAsync(null, method, args, timeout);
            }
            catch
            {
                // Try next method.
            }
        }

        throw new InvalidOperationException("Unable to find a compatible command send method.");
    }

    private static bool TryBuildInvocationArgs(
        ParameterInfo[] parameters,
        Type clientType,
        Type commandType,
        object client,
        string commandVerb,
        string commandArgument,
        string rawCommand,
        out object?[] args)
    {
        args = new object?[parameters.Length];

        for (var i = 0; i < parameters.Length; i++)
        {
            var p = parameters[i];
            var pt = p.ParameterType;

            if (i == 0 && pt.IsAssignableFrom(clientType))
            {
                args[i] = client;
                continue;
            }

            if (pt == typeof(string))
            {
                var name = (p.Name ?? string.Empty).ToLowerInvariant();
                if (name.Contains("arg") || name.Contains("message") || name.Contains("value") || name.Contains("text"))
                {
                    args[i] = commandArgument;
                }
                else if (name.Contains("verb") || name.Contains("name") || name.Contains("command"))
                {
                    args[i] = commandVerb;
                }
                else
                {
                    args[i] = string.IsNullOrWhiteSpace(commandArgument) ? commandVerb : commandArgument;
                }
                continue;
            }

            if (pt == commandType)
            {
                if (!TryCreateCommandObject(commandType, commandVerb, commandArgument, rawCommand, out var cmd))
                {
                    return false;
                }
                args[i] = cmd;
                continue;
            }

            if (pt.IsEnum)
            {
                var enumValue = ParseEnum(pt, commandVerb);
                if (enumValue is null)
                {
                    return false;
                }
                args[i] = enumValue;
                continue;
            }

            if (p.HasDefaultValue)
            {
                args[i] = p.DefaultValue;
                continue;
            }

            if (!pt.IsValueType)
            {
                args[i] = null;
                continue;
            }

            return false;
        }

        return true;
    }

    private static bool TryCreateCommandObject(Type commandType, string commandName, string commandArg, string rawCommand, out object? command)
    {
        command = null;

        foreach (var ctor in commandType.GetConstructors(BindingFlags.Public | BindingFlags.Instance).OrderBy(c => c.GetParameters().Length))
        {
            var ps = ctor.GetParameters();
            try
            {
                if (ps.Length == 0)
                {
                    command = ctor.Invoke(Array.Empty<object?>());
                    break;
                }
                if (ps.Length == 1 && ps[0].ParameterType == typeof(string))
                {
                    command = ctor.Invoke(new object?[] { commandName });
                    break;
                }
                if (ps.Length == 2 && ps[0].ParameterType == typeof(string) && ps[1].ParameterType == typeof(string))
                {
                    command = ctor.Invoke(new object?[] { commandName, commandArg });
                    break;
                }
            }
            catch
            {
                // Try next constructor.
            }
        }

        command ??= Activator.CreateInstance(commandType);
        if (command is null)
        {
            return false;
        }

        SetIfWritable(commandType, command, "Command", commandName);
        SetIfWritable(commandType, command, "Name", commandName);
        SetIfWritable(commandType, command, "Action", commandName);
        SetIfWritable(commandType, command, "Argument", commandArg);
        SetIfWritable(commandType, command, "Value", commandArg);
        SetIfWritable(commandType, command, "Raw", rawCommand);
        SetIfWritable(commandType, command, "Text", rawCommand);

        return true;
    }

    private static void SetIfWritable(Type type, object instance, string propertyName, string value)
    {
        var prop = type.GetProperty(propertyName, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
        if (prop is not null && prop.CanWrite && prop.PropertyType == typeof(string))
        {
            prop.SetValue(instance, value);
        }

        var field = type.GetField(propertyName, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
        if (field is not null && field.FieldType == typeof(string))
        {
            field.SetValue(instance, value);
        }
    }

    private static bool IsSendLike(MethodInfo m)
    {
        var n = m.Name;
        return n.Contains("Send", StringComparison.OrdinalIgnoreCase)
               || n.Contains("Command", StringComparison.OrdinalIgnoreCase)
               || n.Contains("Execute", StringComparison.OrdinalIgnoreCase)
               || n.Contains("Announce", StringComparison.OrdinalIgnoreCase);
    }

    private static int ScoreMethodName(string name, params string[] preferred)
    {
        var score = 0;
        for (var i = 0; i < preferred.Length; i++)
        {
            if (name.Contains(preferred[i], StringComparison.OrdinalIgnoreCase))
            {
                score += 100 - i;
            }
        }
        return score;
    }

    private static object? ParseEnum(Type enumType, string token)
    {
        foreach (var name in Enum.GetNames(enumType))
        {
            if (string.Equals(name, token, StringComparison.OrdinalIgnoreCase))
            {
                return Enum.Parse(enumType, name);
            }
        }
        return null;
    }

    private static async Task<object?> InvokeMethodAsync(object? target, MethodInfo method, object?[] args, TimeSpan timeout)
    {
        var result = method.Invoke(target, args);
        if (result is Task task)
        {
            await task.WaitAsync(timeout);
            return task.GetType().GetProperty("Result")?.GetValue(task);
        }
        return result;
    }

    private static string ToOutput(object? value)
    {
        if (value is null)
        {
            return string.Empty;
        }
        if (value is string s)
        {
            return s;
        }

        var type = value.GetType();
        var preferredProperty = type.GetProperty("Response")
                                ?? type.GetProperty("Message")
                                ?? type.GetProperty("Data")
                                ?? type.GetProperty("Result");

        if (preferredProperty is not null)
        {
            var propertyValue = preferredProperty.GetValue(value);
            if (propertyValue is not null)
            {
                return propertyValue.ToString() ?? string.Empty;
            }
        }

        return value.ToString() ?? string.Empty;
    }
}
