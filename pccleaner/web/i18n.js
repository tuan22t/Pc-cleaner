"use strict";
// Translations. The Vietnamese text is the key; i18n/<lang>.json maps it to
// another language. A missing entry falls back to Vietnamese, never to a blank.
//
//   t("Đã dọn {0} file ({1}).", num(n), fmt(bytes))
//   "{0|file|files}" picks the singular or plural word by the number in {0}.
const I18N = { lang: "vi", dict: {}, locale: "vi-VN" };
const LOCALES = { vi: "vi-VN", en: "en-US" };

function t(key, ...args) {
  let s = (I18N.lang !== "vi" && I18N.dict[key]) || key;
  return s.replace(/\{(\d+)(?:\|([^|}]*)\|([^}]*))?\}/g, (m, i, one, many) => {
    const v = args[+i];
    if (one === undefined) return v === undefined ? m : v;
    const n = Number(String(v).replace(/[^\d-]/g, ""));
    return n === 1 ? one : many;
  });
}

async function loadLang(lang) {
  lang = LOCALES[lang] ? lang : "vi";
  let dict = {};
  if (lang !== "vi") {
    try { dict = await (await fetch(`i18n/${lang}.json`)).json(); } catch (e) { lang = "vi"; }
  }
  I18N.lang = lang; I18N.dict = dict; I18N.locale = LOCALES[lang];
  document.documentElement.lang = lang;
  applyI18n(document);
}

// Static text in index.html: an element marked data-i18n keeps its Vietnamese
// markup as the key; data-i18n-placeholder / -title / -aria-label do the same for attributes.
const norm = (s) => s.trim().replace(/\s+/g, " ");
function applyI18n(root) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    if (!el.dataset.i18nKey) el.dataset.i18nKey = norm(el.innerHTML);
    el.innerHTML = t(el.dataset.i18nKey);
  });
  for (const attr of ["placeholder", "title", "aria-label"]) {
    root.querySelectorAll(`[data-i18n-${attr}]`).forEach((el) => {
      const k = "i18nKey" + attr.replace(/(^|-)(\w)/g, (m, d, c) => c.toUpperCase());
      if (!el.dataset[k]) el.dataset[k] = norm(el.getAttribute(attr) || "");
      el.setAttribute(attr, t(el.dataset[k]));
    });
  }
  if (!document.body.dataset.i18nTitle) document.body.dataset.i18nTitle = document.title;
  document.title = t(document.body.dataset.i18nTitle);
}
