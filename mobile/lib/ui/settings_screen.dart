import 'package:material_ui/material_ui.dart';

import '../i18n.dart';
import '../main.dart' show AppScope;
import '../state.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final st = s.settings;
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    Widget section(String title, List<Widget> children) => Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 6), child: Text(title, style: t.titleSmall?.copyWith(color: cs.primary, fontWeight: FontWeight.w700))),
            Card(child: Column(children: children)),
          ]),
        );
    return Scaffold(
      appBar: AppBar(title: Text(tr('Cài đặt'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          section(tr('Hiển thị'), [
            ListTile(
              leading: const Icon(Icons.translate),
              title: Text(tr('Ngôn ngữ')),
              trailing: SegmentedButton<String>(
                showSelectedIcon: false,
                segments: const [ButtonSegment(value: 'vi', label: Text('Tiếng Việt')), ButtonSegment(value: 'en', label: Text('English'))],
                selected: {st.lang},
                onSelectionChanged: (v) {
                  st.lang = v.first;
                  s.saveSettings();
                },
              ),
            ),
            ListTile(
              leading: const Icon(Icons.dark_mode_outlined),
              title: Text(tr('Giao diện')),
              trailing: DropdownButton<AppTheme>(
                value: st.theme,
                underline: const SizedBox.shrink(),
                items: [
                  DropdownMenuItem(value: AppTheme.system, child: Text(tr('Theo điện thoại'))),
                  DropdownMenuItem(value: AppTheme.light, child: Text(tr('Sáng'))),
                  DropdownMenuItem(value: AppTheme.dark, child: Text(tr('Tối'))),
                ],
                onChanged: (v) {
                  st.theme = v ?? AppTheme.system;
                  s.saveSettings();
                },
              ),
            ),
          ]),
          section(tr('Quét'), [
            ListTile(
              leading: const Icon(Icons.tune),
              title: Text(tr('Độ nhạy khi tìm ảnh giống nhau')),
              subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Slider(
                  min: 2,
                  max: 7,
                  divisions: 5,
                  value: st.threshold.toDouble(),
                  label: '${st.threshold}',
                  onChanged: (v) {
                    st.threshold = v.round();
                    s.saveSettings();
                  },
                ),
                Row(children: [Text(tr('Chặt chẽ')), const Spacer(), Text(tr('Rộng'))]),
                Text(tr('Có hiệu lực từ lần quét sau.'), style: t.bodySmall),
              ]),
            ),
            ListTile(
              leading: const Icon(Icons.movie_outlined),
              title: Text(tr('Video được coi là nặng từ')),
              trailing: DropdownButton<int>(
                value: st.videoMb,
                underline: const SizedBox.shrink(),
                items: [for (final mb in const [50, 100, 200, 500]) DropdownMenuItem(value: mb, child: Text('$mb MB'))],
                onChanged: (v) {
                  st.videoMb = v ?? 100;
                  s.saveSettings();
                },
              ),
            ),
          ]),
          section(tr('An toàn và quyền riêng tư'), [
            ListTile(
              leading: const Icon(Icons.shield_outlined),
              title: Text(tr('Không gì bị xóa ngay')),
              subtitle: Text(tr('Mục đã chọn được chuyển vào Thùng rác của điện thoại và giữ 30 ngày. Điện thoại luôn hỏi bạn xác nhận trước.')),
            ),
            ListTile(
              leading: const Icon(Icons.wifi_off),
              title: Text(s.isIOS ? tr('Không kết nối Internet') : tr('Không có quyền Internet')),
              subtitle: Text(tr('Ảnh, video và kết quả phân tích chỉ nằm trên điện thoại của bạn. Ứng dụng không thu thập dữ liệu nào.')),
            ),
          ]),
          section(tr('Giới thiệu'), [
            ListTile(
              leading: const Icon(Icons.info_outline),
              title: const Text('PC Cleaner'),
              subtitle: Text(tr('Phiên bản {0}. Miễn phí, nhờ sự tài trợ của {1}.', [appVersion, s.promo?.sponsorFor(currentLang) ?? 'Tân An Palace'])),
            ),
          ]),
        ],
      ),
    );
  }
}

const appVersion = '1.0.0';
