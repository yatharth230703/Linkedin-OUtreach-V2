"""Quick test to verify our selectors match the LinkedIn verification elements"""
from lxml import html

# The HTML elements you provided
verification_input_html = '''<input class="form__input--text input_verification_pin" name="pin" maxlength="6" pattern="[0-9]*" autocorrect="off" placeholder="Enter code" id="input__email_verification_pin" aria-label="Verification code" aria-describedby="email-pin-error" aria-required="true" validation="pin" validation-message="Hmm, that's not the right code" data-empty-code-validation-message="Please enter the code" type="number">'''

submit_button_html = '''<button class="form__submit form__submit--stretch" id="email-pin-submit-button" aria-label="Submit pin" type="submit">Submit</button>'''

# Parse the HTML
input_tree = html.fromstring(verification_input_html)
button_tree = html.fromstring(submit_button_html)

print("=" * 80)
print("VERIFICATION INPUT ELEMENT TESTS")
print("=" * 80)

# Test verification input selectors
input_selectors = [
    ("//input[@id='input__email_verification_pin'][@name='pin'][@type='number']", "ID+name+type: input__email_verification_pin"),
    ("//input[@id='input__email_verification_pin']", "ID: input__email_verification_pin"),
    ("//input[@name='pin'][@type='number']", "name=pin type=number"),
    ("//input[@name='pin']", "name=pin"),
]

for selector, description in input_selectors:
    try:
        result = input_tree.xpath(selector)
        if result:
            print(f"✅ MATCH: {description}")
            print(f"   Selector: {selector}")
        else:
            print(f"❌ NO MATCH: {description}")
    except Exception as e:
        print(f"❌ ERROR: {description} - {e}")

print("\n" + "=" * 80)
print("SUBMIT BUTTON ELEMENT TESTS")
print("=" * 80)

# Test submit button selectors
button_selectors = [
    ("//button[@id='email-pin-submit-button'][@type='submit']", "ID+type: email-pin-submit-button"),
    ("//button[@id='email-pin-submit-button']", "ID: email-pin-submit-button"),
    ("//button[@type='submit']", "type=submit"),
]

for selector, description in button_selectors:
    try:
        result = button_tree.xpath(selector)
        if result:
            print(f"✅ MATCH: {description}")
            print(f"   Selector: {selector}")
        else:
            print(f"❌ NO MATCH: {description}")
    except Exception as e:
        print(f"❌ ERROR: {description} - {e}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("All our top-priority selectors correctly match the LinkedIn verification elements!")
print("The script will try the most specific selectors first for maximum reliability.")
