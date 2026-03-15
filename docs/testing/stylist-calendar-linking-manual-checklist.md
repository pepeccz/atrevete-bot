# Manual UI Testing Checklist: Stylist Calendar Linking

## Overview
This checklist verifies the frontend behavior for the stylist calendar linking fix. Use this document to manually test the admin panel UI changes related to calendar conflict prevention.

## Prerequisites
- [ ] Access to admin panel at `http://localhost:3000` (or production URL)
- [ ] Admin credentials (username/password)
- [ ] At least 2 stylists configured with different Google Calendars
- [ ] Multiple Google Calendars available in your Google account

---

## Test Suite 1: Calendar Dropdown State Management

### Test 1.1: Available Calendars Are Selectable
**Objective**: Verify free calendars can be selected

**Steps**:
1. Navigate to **Stylists** page
2. Click **"Nuevo Estilista"** button
3. Open the **"Calendario Google"** dropdown

**Expected Result**:
- [ ] Dropdown opens without errors
- [ ] Calendars not assigned to any stylist show as enabled/selectable
- [ ] Each calendar displays normally (no disabled styling)

### Test 1.2: Occupied Calendars Are Disabled
**Objective**: Verify calendars assigned to other stylists are visually blocked

**Prerequisites**:
- Stylist A has Calendar X assigned

**Steps**:
1. Navigate to **Stylists** page
2. Click **"Nuevo Estilista"** button
3. Open the **"Calendario Google"** dropdown

**Expected Result**:
- [ ] Calendar X (assigned to Stylist A) appears in the dropdown
- [ ] Calendar X has visual "occupied" state (e.g., grayed out, disabled cursor)
- [ ] Cannot select Calendar X (click does nothing or is blocked)
- [ ] Tooltip/badge shows "Asignado a: [Nombre del Estilista]"

### Test 1.3: Current Stylist's Calendar Remains Selectable on Edit
**Objective**: Verify stylist can keep their current calendar when editing

**Prerequisites**:
- Stylist A has Calendar X assigned

**Steps**:
1. Navigate to **Stylists** page
2. Click **"Editar"** on Stylist A's row
3. Open the **"Calendario Google"** dropdown

**Expected Result**:
- [ ] Calendar X appears in dropdown as selected/current
- [ ] Calendar X is **enabled** (not disabled/grayed out)
- [ ] Can re-select Calendar X without errors
- [ ] Form submission with unchanged Calendar X succeeds

### Test 1.4: Switching to Another's Calendar is Blocked
**Objective**: Verify attempting to switch to an occupied calendar shows clear feedback

**Prerequisites**:
- Stylist A has Calendar X assigned
- Stylist B has Calendar Y assigned

**Steps**:
1. Navigate to **Stylists** page
2. Click **"Editar"** on Stylist A's row
3. Attempt to select Calendar Y (occupied by Stylist B)

**Expected Result**:
- [ ] Calendar Y is visibly disabled in dropdown
- [ ] Cannot select Calendar Y
- [ ] Visual indicator shows "Asignado a: Stylist B"

---

## Test Suite 2: Conflict Error Handling

### Test 2.1: Inline 409 Error Display
**Objective**: Verify user sees clear error message when backend rejects conflict

**Prerequisites**:
- Two browser sessions or quick timing
- Stylist A has Calendar X

**Steps**:
1. In Browser 1: Open Stylist B's edit modal
2. In Browser 2: Delete Stylist A (freeing Calendar X)
3. Quickly in Browser 1: Try to assign Calendar X to Stylist B
4. Or use developer tools to simulate race condition

**Expected Result**:
- [ ] Modal stays open (no redirect)
- [ ] Inline error message appears in modal
- [ ] Error message is in Spanish: "Este calendario ya está asignado a: [Nombre]"
- [ ] Form fields remain filled (no data loss)
- [ ] Can close modal or retry

### Test 2.2: Error Recovery Flow
**Objective**: Verify user can recover from conflict error

**Steps**:
1. Trigger a 409 error (see Test 2.1)
2. Click a different, available calendar
3. Click **"Guardar"**

**Expected Result**:
- [ ] Error message clears when selecting different calendar
- [ ] Save succeeds with new calendar choice
- [ ] Modal closes
- [ ] Stylist list updates with new calendar

### Test 2.3: Multiple Conflicting Stylists in Error
**Objective**: Verify error shows all conflicting stylists if applicable

**Note**: This tests the edge case where data inconsistency exists

**Steps**:
1. Attempt to assign a calendar to a stylist
2. If backend returns multiple stylist names in conflict

**Expected Result**:
- [ ] Error message lists all conflicting stylist names
- [ ] Format: "Este calendario ya está asignado a: Ana, Maria, Laura"

---

## Test Suite 3: Visual States and Feedback

### Test 3.1: Calendar State Legend/Key
**Objective**: Verify users understand calendar state indicators

**Steps**:
1. Open any stylist create/edit modal
2. Open the calendar dropdown

**Expected Result**:
- [ ] Visual distinction between states:
  - **Available**: Normal styling, selectable
  - **Current**: Highlighted/selected indicator
  - **Occupied**: Disabled/grayed, shows owner name

### Test 3.2: Tooltip on Hover (if implemented)
**Objective**: Verify tooltips provide additional context

**Steps**:
1. Open calendar dropdown
2. Hover over an occupied calendar option

**Expected Result**:
- [ ] Tooltip appears showing "Asignado a: [Stylist Name]"
- [ ] Tooltip is readable and positioned correctly
- [ ] Tooltip disappears when mouse leaves

### Test 3.3: Loading States
**Objective**: Verify loading state during form submission

**Steps**:
1. Fill out new stylist form
2. Click **"Guardar"**

**Expected Result**:
- [ ] Save button shows loading spinner/disabled state
- [ ] Button text changes to "Guardando..." or similar
- [ ] Cannot submit form multiple times
- [ ] On success: modal closes, list refreshes

---

## Test Suite 4: Edge Cases

### Test 4.1: Creating Stylist with No Available Calendars
**Objective**: Verify graceful handling when all calendars are occupied

**Prerequisites**:
- All Google Calendars assigned to existing stylists

**Steps**:
1. Navigate to **Stylists** page
2. Click **"Nuevo Estilista"**
3. Open calendar dropdown

**Expected Result**:
- [ ] Dropdown opens (no crash)
- [ ] All calendars shown as occupied
- [ ] User can still submit with one of their calendars (if editing)
- [ ] For new stylist: appropriate messaging about no available calendars

### Test 4.2: Rapid Form Submission
**Objective**: Verify no double-submit issues

**Steps**:
1. Fill out new stylist form
2. Rapidly click **"Guardar"** 3+ times

**Expected Result**:
- [ ] Only one request sent to backend
- [ ] Only one stylist created
- [ ] No 409 errors from race condition

### Test 4.3: Browser Back Button After Conflict
**Objective**: Verify state consistency after using browser back

**Steps**:
1. Create a stylist successfully
2. Navigate away from stylists page
3. Click browser back button

**Expected Result**:
- [ ] Stylists list shows current data
- [ ] Newly created stylist appears
- [ ] No stale/cached conflict states

---

## Test Suite 5: Regression Tests

### Test 5.1: Existing Stylist CRUD Still Works
**Objective**: Verify no regressions in basic stylist management

**Steps**:
1. Create a stylist with free calendar
2. Edit the stylist's name (not calendar)
3. Delete the stylist

**Expected Result**:
- [ ] Create succeeds
- [ ] Edit succeeds
- [ ] Delete succeeds
- [ ] All operations show appropriate success messages

### Test 5.2: Non-Calendar Fields Unaffected
**Objective**: Verify conflict handling doesn't affect other fields

**Steps**:
1. Edit an existing stylist
2. Change only the color field
3. Save

**Expected Result**:
- [ ] Save succeeds
- [ ] Color updates correctly
- [ ] No conflict validation triggered unnecessarily

### Test 5.3: Other Admin Features Unaffected
**Objective**: Verify stylists page changes don't break other pages

**Steps**:
1. Navigate to **Customers** page
2. Navigate to **Appointments** page
3. Navigate to **Services** page

**Expected Result**:
- [ ] All pages load without errors
- [ ] No console errors related to stylist changes
- [ ] All CRUD operations work normally

---

## Bug Report Template

If you find an issue during testing, please report using this format:

```
**Test Case**: [Test number from checklist]
**Severity**: [Critical/High/Medium/Low]
**Environment**: [Local/Staging/Production]
**Browser**: [Chrome/Firefox/Safari/Edge]

**Steps to Reproduce**:
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Expected Behavior**:
[What should happen]

**Actual Behavior**:
[What actually happens]

**Screenshots**:
[Attach if applicable]

**Console Errors**:
```
[Copy any browser console errors]
```
```

---

## Sign-off

**Tester**: ___________________  **Date**: ___________________

**Results**:
- [ ] All tests passed
- [ ] Some tests failed (see bug reports)
- [ ] Not tested (explain): ___________________

**Notes**:
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
