# Renewal Request Edit Feature - Implementation Summary

## Overview
Implemented admin capability to edit renewal request dates before approval. Allows admins to customize renewal start/end dates for members who rejoin after expiry, addressing the specific use case: "if a student after expiry skips for 10 days and joins again after 10 days the renew should happen from 10 days after expiry, but I should be able to edit it."

## Changes Made

### 1. Database Model - [models/renewal_request.py](models/renewal_request.py)
**Added two new optional date columns:**
- `proposed_start_date` (Date, nullable=True)
- `proposed_end_date` (Date, nullable=True)

These columns store the custom renewal dates set by admin before approval.

### 2. Database Migration - [migrations/versions/20260821101124_add_renewal_request_proposed_dates.py](migrations/versions/20260821101124_add_renewal_request_proposed_dates.py)
**Created new migration to:**
- Add `proposed_start_date` column to renewal_requests table
- Add `proposed_end_date` column to renewal_requests table
- Provides downgrade path to remove columns if needed

**To apply migration on EC2:**
```bash
cd /home/ubuntu/prerna.v02
flask db upgrade
# OR
alembic upgrade head
```

### 3. Backend Routes - [routes/admissions.py](routes/admissions.py)

#### A. Updated `_apply_member_renewal()` function (line 270)
**Signature change:**
```python
def _apply_member_renewal(member, duration_months, custom_start_date=None, custom_end_date=None)
```

**Behavior:**
- If `custom_start_date` and `custom_end_date` are provided, use them directly
- Otherwise, use default logic: `base_date = member.membership_end_date or today`, if base_date < today, reset to today
- Supports both standard renewal and admin-customized renewal flows

#### B. New `edit_renewal_request()` route (line 1221)
**Route:** `GET/POST /admissions/renewal-requests/<int:request_id>/edit`
**Authorization:** Admin only
**Functionality:**
- GET: Display form with member details and current proposed dates (if set)
- POST: Validate and save custom renewal dates
- Validation: 
  - Dates must be in valid format (yyyy-mm-dd)
  - End date cannot be before start date
  - Start date cannot be in future
- Redirect to renewal_requests list on success

#### C. Updated `approve_renewal_request()` route (line 1287)
**Changes:**
- Checks if renewal_request has custom proposed dates
- If yes: calls `_apply_member_renewal(member, 1, proposed_start_date, proposed_end_date)`
- If no: calls `_apply_member_renewal(member, renewal_request.duration_months)` with default logic
- Updated success message to show membership end date

#### D. Updated `renewal_requests()` route (line 1205)
**No code changes, but now displays:**
- Updated template with Edit and Approve buttons

### 4. Frontend Templates

#### A. New [templates/admissions/edit_renewal_request.html](templates/admissions/edit_renewal_request.html)
**Layout:**
- Member information section (readonly): ID, Name, Lab, Current Membership End Date
- Renewal details form:
  - Proposed Start Date (date input, required)
  - Proposed End Date (date input, required)
- Informational alert explaining flexibility
- Timeline example showing use case (e.g., expired Aug 11, rejoins Aug 21)
- Save and Cancel buttons
- JavaScript auto-calculates 1-month end date when start date changes

**Features:**
- Bootstrap 5 styling with card layout
- Date format: yyyy-mm-dd
- Helpful context about renewal flexibility
- Example timeline for member rejoin scenarios

#### B. Updated [templates/admissions/renewal_requests.html](templates/admissions/renewal_requests.html)
**Changes:**
- Added "Proposed Dates" column showing customized dates if set
- Split action buttons into Edit and Approve
- Edit button links to `/admissions/renewal-requests/<id>/edit`
- Approve button now includes confirmation dialog showing current dates
- Updated table header and styling
- Added workflow explanation at bottom

**Display:**
```
Requested At | Member | ID | Requested By | Proposed Dates | Status | Actions
...          | Name   | M1 | User Name    | 2026-08-21 to  | Pending | [Edit] [Approve]
             |        |    |              | 2026-09-21     |        |
```

## Workflow

### User Journey for Admin:
1. Member sends renewal request → status="Pending"
2. Admin navigates to "Renewal Requests" page
3. Admin clicks "Edit" button on pending request
4. Edit form loads with:
   - Member details (readonly)
   - Default proposed start date (member's membership_end_date or today)
   - Empty end date
5. Admin customizes dates:
   - Example: Member expired Aug 11, rejoin today Aug 21
   - Admin sets: Start = Aug 12, End = Sep 12 (or any date they prefer)
6. Admin saves changes
7. Admin returns to renewal requests list
8. Admin clicks "Approve" to finalize renewal with custom dates
9. Membership is updated with custom dates
10. MembershipHistory records the renewal with custom dates

### Code Flow on Approval:
```
approve_renewal_request() 
  → Check if proposed_start_date AND proposed_end_date exist
  → Yes: _apply_member_renewal(member, 1, start_date, end_date)
  → No: _apply_member_renewal(member, duration_months)  # default logic
  → Update RenewalRequest.status = "Approved"
  → Record reviewed_at and reviewed_by_user_id
  → Flash success with membership_end_date
```

## Testing Checklist

- [ ] Migration applied successfully on production
- [ ] Renewal request model has new columns
- [ ] Edit renewal request route loads form correctly
- [ ] Form validates proposed dates (can't be after start date, etc.)
- [ ] Proposed dates are saved to database
- [ ] Approve button reads proposed dates if set
- [ ] Membership dates updated correctly with custom dates
- [ ] MembershipHistory records renewal with custom dates
- [ ] Admin can see "Proposed Dates" in renewal_requests list
- [ ] Confirmation dialog shows dates before approval

## Files Modified/Created

### Created:
1. [templates/admissions/edit_renewal_request.html](templates/admissions/edit_renewal_request.html) - New edit form template
2. [migrations/versions/20260821101124_add_renewal_request_proposed_dates.py](migrations/versions/20260821101124_add_renewal_request_proposed_dates.py) - Database migration

### Modified:
1. [models/renewal_request.py](models/renewal_request.py) - Added proposed date columns
2. [routes/admissions.py](routes/admissions.py) - Updated _apply_member_renewal, added edit_renewal_request, updated approve_renewal_request
3. [templates/admissions/renewal_requests.html](templates/admissions/renewal_requests.html) - Added Edit button and proposed dates column

## Production Deployment Steps

1. **Backup database:**
   ```bash
   pg_dump prerna_db > prerna_db_backup_$(date +%Y%m%d).sql
   ```

2. **Pull code changes:**
   ```bash
   cd /home/ubuntu/prerna.v02
   git pull origin attendancefix  # Assuming changes are in this branch
   ```

3. **Apply migration:**
   ```bash
   flask db upgrade
   ```

4. **Restart application:**
   ```bash
   sudo systemctl restart prerna-gunicorn
   ```

5. **Verify:**
   - Navigate to Admissions → Renewal Requests
   - Click Edit on a renewal request
   - Verify form displays and saves dates correctly

## Rollback Plan

If issues occur:

1. **Revert code:**
   ```bash
   git revert <commit-hash>
   git push origin attendancefix
   ```

2. **Downgrade database:**
   ```bash
   flask db downgrade  # Removes the two new columns
   ```

3. **Restart application:**
   ```bash
   sudo systemctl restart prerna-gunicorn
   ```

## Notes

- All new dates are optional - existing renewal logic still works if admin doesn't customize
- Dates can be in the past (allows admin flexibility for backdated renewals)
- Proposed dates are only used if BOTH start and end dates are set
- If only one date is set, default calculation is used
- MembershipHistory records the actual renewal dates used
- UI clearly shows which dates are customized vs. default
