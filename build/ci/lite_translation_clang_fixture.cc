// Models the platform conditions in the two translation patches.
// Compile only as a small diagnostic fixture, not as part of Brave.
#define BUILDFLAG_INTERNAL_IS_MAC() (1)
#define BUILDFLAG_CAT_INDIRECT(a, b) a##b
#define BUILDFLAG_CAT(a, b) BUILDFLAG_CAT_INDIRECT(a, b)
#define BUILDFLAG(flag) BUILDFLAG_CAT(BUILDFLAG_INTERNAL_, flag)()

struct Value {
  bool GetBool() const;
};
struct Pref {
  const Value* GetValue() const;
  bool IsManaged() const;
};
struct Prefs {
  bool GetBoolean(int) const;
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
  bool translation_pending() const;
  const char* GetVisibleURL() const;
  void SetTranslationType(int);
  void Translate() {
    if (BUILDFLAG(IS_MAC)) return;
    if (translation_pending()) return;
    SetTranslationType(1);
  }
  void Initiate() {
    if (BUILDFLAG(IS_MAC)) return;
    const char* page_url = GetVisibleURL();
    SetTranslationType(page_url ? 1 : 0);
  }
};
