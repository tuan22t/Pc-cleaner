import 'dart:io';

import 'package:material_ui/material_ui.dart';
import 'package:path_provider/path_provider.dart';

import 'core/action_log.dart';
import 'core/scanner.dart';
import 'data/native_media_source.dart';
import 'data/demo_media_source.dart';
import 'data/media_source.dart';
import 'i18n.dart';
import 'state.dart';
import 'ui/explore_screen.dart';
import 'ui/history_screen.dart';
import 'ui/home_screen.dart';
import 'ui/settings_screen.dart';

/// Build with `--dart-define=DEMO=true` to run on made-up photos.
const bool demoMode = bool.fromEnvironment('DEMO');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await loadTranslations();
  final dir = await getApplicationSupportDirectory();
  MediaSource source;
  PermissionState? perm;
  if (demoMode || !(Platform.isAndroid || Platform.isIOS)) {
    source = DemoMediaSource();
  } else {
    final a = NativeMediaSource(platform: Platform.isIOS ? 'ios' : 'android');
    source = a;
    try {
      perm = await a.permissionState();
    } catch (_) {}
  }
  final state = AppState(
    source: source,
    log: ActionLog(File('${dir.path}/nhat-ky.jsonl')),
    cache: AnalysisCache(File('${dir.path}/phan-tich.json')),
    settingsFile: File('${dir.path}/cai-dat.json'),
  );
  await state.init(knownPermission: perm);
  runApp(PcCleanerApp(state: state));
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;
}

const brandBlue = Color(0xFF2F6FED);

ThemeData buildTheme(Brightness b) {
  final scheme = ColorScheme.fromSeed(seedColor: brandBlue, brightness: b, primary: b == Brightness.light ? brandBlue : null);
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    fontFamily: 'Roboto',
    scaffoldBackgroundColor: b == Brightness.light ? const Color(0xFFF5F6F8) : const Color(0xFF11151D),
    cardTheme: CardThemeData(
      elevation: 0,
      color: b == Brightness.light ? Colors.white : const Color(0xFF1A202B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      margin: EdgeInsets.zero,
    ),
    appBarTheme: const AppBarTheme(centerTitle: false),
  );
}

class PcCleanerApp extends StatelessWidget {
  const PcCleanerApp({super.key, required this.state, this.initialTab = 0});
  final AppState state;
  final int initialTab;

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: ListenableBuilder(
        listenable: state,
        builder: (context, _) => MaterialApp(
          title: 'PC Cleaner',
          debugShowCheckedModeBanner: false,
          theme: buildTheme(Brightness.light),
          darkTheme: buildTheme(Brightness.dark),
          themeMode: switch (state.settings.theme) {
            AppTheme.light => ThemeMode.light,
            AppTheme.dark => ThemeMode.dark,
            AppTheme.system => ThemeMode.system,
          },
          locale: Locale(state.settings.lang),
          supportedLocales: const [Locale('vi'), Locale('en')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: MainShell(initialTab: initialTab),
        ),
      ),
    );
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key, this.initialTab = 0});
  final int initialTab;

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  late int _tab = widget.initialTab;

  @override
  Widget build(BuildContext context) {
    AppScope.of(context); // rebuild on language change
    final pages = [
      HomeScreen(onOpenTab: (t) => setState(() => _tab = t)),
      const HistoryScreen(),
      const ExploreScreen(),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: _tab, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [
          NavigationDestination(icon: const Icon(Icons.cleaning_services_outlined), selectedIcon: const Icon(Icons.cleaning_services), label: tr('Dọn dẹp')),
          NavigationDestination(icon: const Icon(Icons.history), label: tr('Nhật ký')),
          NavigationDestination(icon: const Icon(Icons.explore_outlined), selectedIcon: const Icon(Icons.explore), label: tr('Khám phá')),
          NavigationDestination(icon: const Icon(Icons.settings_outlined), selectedIcon: const Icon(Icons.settings), label: tr('Cài đặt')),
        ],
      ),
    );
  }
}
