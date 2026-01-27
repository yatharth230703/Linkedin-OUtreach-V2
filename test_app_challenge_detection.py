"""Test LinkedIn App Challenge Detection"""
from lxml import html

# Sample HTML from the app challenge page
app_challenge_html = '''
<h1 class="header__content__heading__inapp">
    Check your LinkedIn app
</h1>
<p class="header__content__subheading">
    We sent a notification to your signed in devices.
    Open your LinkedIn app and tap <b>Yes</b> to confirm your sign-in attempt.
</p>
<button class="form__submit__inapp" id="reset-password-submit-button">
    Resend
</button>
<a id="try-another-way" tabindex="0" role="link">
    Verify using SMS
</a>
'''

# Parse the HTML
tree = html.fromstring(app_challenge_html)

print("=" * 80)
print("LINKEDIN APP CHALLENGE DETECTION TESTS")
print("=" * 80)

# Test app challenge selectors
app_challenge_selectors = [
    ("//h1[contains(text(), 'Check your LinkedIn app')]", "heading: Check your LinkedIn app"),
    ("//h1[@class='header__content__heading__inapp']", "class: header__content__heading__inapp"),
    ("//p[contains(text(), 'We sent a notification to your signed in devices')]", "text: notification sent"),
    ("//p[@class='header__content__subheading']", "class: header__content__subheading"),
    ("//button[@id='reset-password-submit-button']", "ID: reset-password-submit-button"),
    ("//button[@class='form__submit__inapp']", "class: form__submit__inapp"),
    ("//a[@id='try-another-way']", "ID: try-another-way"),
    ("//a[contains(text(), 'Verify using SMS')]", "text: Verify using SMS"),
]

detected_count = 0
for selector, description in app_challenge_selectors:
    try:
        result = tree.xpath(selector)
        if result:
            print(f"✅ MATCH: {description}")
            print(f"   Selector: {selector}")
            detected_count += 1
        else:
            print(f"❌ NO MATCH: {description}")
    except Exception as e:
        print(f"❌ ERROR: {description} - {e}")

print(f"\n" + "=" * 80)
print(f"SUMMARY: {detected_count}/{len(app_challenge_selectors)} selectors matched")
print("=" * 80)

if detected_count >= 2:
    print("✅ App challenge detection will work reliably!")
    print("The script will detect this screen and prompt user to check their mobile app.")
else:
    print("⚠️ May need additional selectors for reliable detection")

print("\nFlow after detection:")
print("1. 📱 Detect app challenge screen")
print("2. 🔔 Notify user to check mobile app")
print("3. ⏳ Wait up to 2 minutes for approval")
print("4. ✅ Continue with normal login flow (OTP/verification if needed)")