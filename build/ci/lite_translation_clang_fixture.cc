// Model the platform conditions in Brave's translation patches.
// This is a standalone compiler and behavior check, not a Brave build.
#ifndef LITE_TEST_IS_MAC
#error LITE_TEST_IS_MAC must be specified as 0 or 1
#endif
#define BUILDFLAG_INTERNAL_IS_MAC() (LITE_TEST_IS_MAC)
#define BUILDFLAG_CAT_INDIRECT(a, b) a##b
#define BUILDFLAG_CAT(a, b) BUILDFLAG_CAT_INDIRECT(a, b)
#define BUILDFLAG(flag) BUILDFLAG_CAT(BUILDFLAG_INTERNAL_, flag)()

struct Value {
  bool GetBool() const { return false; }
};
struct Pref {
  const Value* GetValue() const { return &value; }
  bool IsManaged() const { return false; }
  Value value;
};
struct Prefs {
  bool GetBoolean(int) const { return true; }
};
namespace prefs {
constexpr int kOfferTranslateEnabled = 1;
}
struct TranslatePrefs {
  const Prefs* prefs_;
  bool IsOfferTranslateEnabled() const {
    return prefs_->GetBoolean(prefs::kOfferTranslateEnabled) && !BUILDFLAG(IS_MAC);
  }
  bool IsTranslateAllowedByPolicy(const Pref* pref) const {
    return (pref->GetValue()->GetBool() || !pref->IsManaged()) && !BUILDFLAG(IS_MAC);
  }
};
struct TranslationManager {
  int calls = 0;
  bool translation_pending() const { return false; }
  const char* GetVisibleURL() const { return "https://example.invalid"; }
  void SetTranslationType(int) { ++calls; }
  void Translate() {
#if BUILDFLAG(IS_MAC)
    return;
#else
    if (translation_pending()) return;
    SetTranslationType(1);
#endif
  }
  void Initiate() {
#if BUILDFLAG(IS_MAC)
    return;
#else
    const char* page_url = GetVisibleURL();
    SetTranslationType(page_url ? 1 : 0);
#endif
  }
};

int main() {
  Prefs prefs_store;
  Pref pref;
  TranslatePrefs translate_prefs{&prefs_store};
  TranslationManager manager;
  manager.Translate();
  manager.Initiate();
  const bool expected_enabled = !LITE_TEST_IS_MAC;
  return translate_prefs.IsOfferTranslateEnabled() != expected_enabled ||
         translate_prefs.IsTranslateAllowedByPolicy(&pref) != expected_enabled ||
         manager.calls != (LITE_TEST_IS_MAC ? 0 : 2);
}
