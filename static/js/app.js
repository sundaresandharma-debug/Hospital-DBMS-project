/* ==========================================================================
   PulseCare+ Hospital Management System - Complete Client Application Logic
   ========================================================================== */

let activeUser = null;
let activeView = 'dashboard';
let hospitalBedsCache = [];
let pharmacyInventoryCache = [];
let siteInfo = { business: {}, demo_mode: false, staff_signup_enabled: false, consultation_fee: 0 };

// Initialize app when DOM is fully loaded
document.addEventListener('DOMContentLoaded', async () => {
  initCookieConsent();
  await loadSiteInfo();
  await verifySessionState();
  if (activeUser) {
    applyRolePermissions();
    refreshDashboard();
  }
});

/* --------------------------------------------------------------------------
   1. Password Toggle & Authentication Handlers
   -------------------------------------------------------------------------- */

function togglePasswordVisibility(inputFieldId, eyeIconId, toggleButton) {
  const passwordInput = document.getElementById(inputFieldId);
  const eyeIcon = document.getElementById(eyeIconId);

  if (!passwordInput || !eyeIcon) return;

  const willShow = passwordInput.type === 'password';
  passwordInput.type = willShow ? 'text' : 'password';
  eyeIcon.classList.toggle('fa-eye', !willShow);
  eyeIcon.classList.toggle('fa-eye-slash', willShow);
  if (toggleButton) {
    toggleButton.setAttribute('aria-pressed', String(willShow));
    toggleButton.setAttribute('aria-label', willShow ? 'Hide password' : 'Show password');
  }
}

function switchAuthTab(targetTab) {
  const isLogin = targetTab === 'login';
  const loginTabBtn = document.getElementById('tab-login');
  const signupTabBtn = document.getElementById('tab-signup');

  document.getElementById('login-form').classList.toggle('hidden', !isLogin);
  document.getElementById('signup-form').classList.toggle('hidden', isLogin);
  loginTabBtn.classList.toggle('active', isLogin);
  signupTabBtn.classList.toggle('active', !isLogin);
  loginTabBtn.setAttribute('aria-selected', String(isLogin));
  signupTabBtn.setAttribute('aria-selected', String(!isLogin));
  loginTabBtn.tabIndex = isLogin ? 0 : -1;
  signupTabBtn.tabIndex = isLogin ? -1 : 0;
}

// Arrow keys move between the Sign In / Create Account tabs (WAI-ARIA tabs pattern)
function handleAuthTabKeys(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const target = event.currentTarget.id === 'tab-login' ? 'signup' : 'login';
  const goTo = event.key === 'Home' ? 'login' : event.key === 'End' ? 'signup' : target;
  switchAuthTab(goTo);
  document.getElementById(`tab-${goTo}`).focus();
}

function skipToMain(event) {
  event.preventDefault();
  const main = activeUser ? document.getElementById('main-content') : document.getElementById('auth-screen');
  if (main) main.focus();
}

/* --------------------------------------------------------------------------
   Business details, demo mode & sign-up consent
   -------------------------------------------------------------------------- */

async function loadSiteInfo() {
  try {
    const response = await fetch('/api/site-info');
    siteInfo = await response.json();
  } catch (err) {
    console.error('Error loading site info:', err);
  }

  const biz = siteInfo.business || {};
  const detailsHtml = `
    <p><strong>${escapeHtml(biz.trading_name)}</strong> is operated by ${escapeHtml(biz.name)}, ${escapeHtml(biz.address)}.</p>
    <p>Registration: ${escapeHtml(biz.registration)} &middot; Tax ID: ${escapeHtml(biz.tax_id)} &middot; Contact: ${escapeHtml(biz.email)} &middot; ${escapeHtml(biz.phone)}</p>
    <p>In a medical emergency, call your local emergency number. This portal is not an emergency service.</p>
  `;
  document.querySelectorAll('.business-details').forEach((el) => { el.innerHTML = detailsHtml; });

  document.getElementById('demo-banner').classList.toggle('hidden', !siteInfo.demo_mode);
  document.querySelectorAll('.quick-demo-accounts').forEach((el) => el.classList.toggle('hidden', !siteInfo.demo_mode));

  const staffRadio = document.querySelector('input[name="signup-role"][value="staff"]');
  if (staffRadio && !siteInfo.staff_signup_enabled) {
    staffRadio.disabled = true;
    staffRadio.closest('.role-card').querySelector('small').textContent = 'Accounts issued by your administrator';
  }

  document.querySelectorAll('.con-fee-display').forEach((el) => {
    el.textContent = `₹${Number(siteInfo.consultation_fee || 0).toFixed(2)}`;
  });
}

function updateSignupRole() {
  const role = document.querySelector('input[name="signup-role"]:checked').value;
  document.getElementById('staff-invite-group').classList.toggle('hidden', role !== 'staff');
  document.getElementById('health-consent-row').classList.toggle('hidden', role !== 'patient');
}

function updateSignupAgeGroup() {
  const selected = document.querySelector('input[name="signup-age-group"]:checked');
  const isMinor = selected && selected.value === 'minor';
  document.getElementById('guardian-fields').classList.toggle('hidden', !isMinor);
  document.getElementById('signup-guardian-name').required = isMinor;
  document.getElementById('signup-guardian-consent').required = isMinor;
}

function fillDemo(username, password) {
  document.getElementById('login-username').value = username;
  document.getElementById('login-password').value = password;
}

async function handleLogin(event) {
  event.preventDefault();
  const usernameInput = document.getElementById('login-username').value.trim();
  const passwordInput = document.getElementById('login-password').value.trim();

  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: usernameInput, password: passwordInput })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Login failed');

    activeUser = payload.user;
    notifyUser(`Welcome back, ${activeUser.name}!`, 'success');
    renderAuthenticatedPortal();
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

async function handleSignup(event) {
  event.preventDefault();
  const nameVal = document.getElementById('signup-name').value.trim();
  const mobileVal = document.getElementById('signup-mobile').value.trim();
  const usernameVal = document.getElementById('signup-username').value.trim();
  const passwordVal = document.getElementById('signup-password').value.trim();
  const roleVal = document.querySelector('input[name="signup-role"]:checked').value;
  const ageGroup = document.querySelector('input[name="signup-age-group"]:checked');

  if (roleVal === 'patient' && !document.getElementById('signup-health-consent').checked) {
    notifyUser('Please give explicit consent to the processing of health information to register as a patient.', 'error');
    return;
  }

  try {
    const response = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameVal,
        mobile_no: mobileVal,
        username: usernameVal,
        password: passwordVal,
        role: roleVal,
        staff_invite_code: document.getElementById('signup-invite-code').value.trim(),
        age_group: ageGroup ? ageGroup.value : null,
        guardian_name: document.getElementById('signup-guardian-name').value.trim(),
        guardian_consent: document.getElementById('signup-guardian-consent').checked,
        accept_terms: document.getElementById('signup-accept-terms').checked,
        health_data_consent: roleVal === 'patient' && document.getElementById('signup-health-consent').checked,
        marketing_opt_in: document.getElementById('signup-marketing').checked
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Registration failed');

    activeUser = payload.user;
    notifyUser(`Account registered as ${roleVal.toUpperCase()}!`, 'success');
    renderAuthenticatedPortal();
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

async function verifySessionState() {
  try {
    const response = await fetch('/api/auth/me');
    const data = await response.json();
    if (data.authenticated) {
      activeUser = data.user;
      renderAuthenticatedPortal();
    } else {
      renderUnauthenticatedView();
    }
  } catch (err) {
    renderUnauthenticatedView();
  }
}

async function handleLogout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  activeUser = null;
  notifyUser('You have been logged out.', 'info');
  renderUnauthenticatedView();
}

function renderUnauthenticatedView() {
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('app-screen').classList.add('hidden');
}

function renderAuthenticatedPortal() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.remove('hidden');

  document.getElementById('display-user-name').textContent = activeUser.name || activeUser.username;
  document.getElementById('display-user-handle').textContent = `@${activeUser.username}`;

  const initials = (activeUser.name || activeUser.username).slice(0, 2).toUpperCase();
  document.getElementById('user-avatar-initials').textContent = initials;

  const roleIndicator = document.getElementById('user-role-badge');
  roleIndicator.textContent = activeUser.role.toUpperCase();
  if (activeUser.role === 'patient') {
    roleIndicator.classList.add('role-patient');
  } else {
    roleIndicator.classList.remove('role-patient');
  }

  applyRolePermissions();
  switchView('dashboard');
}

function applyRolePermissions() {
  const isStaff = activeUser && activeUser.role === 'staff';

  document.querySelectorAll('.staff-only').forEach((elem) => {
    elem.classList.toggle('hidden', !isStaff);
  });
  document.querySelectorAll('.patient-only').forEach((elem) => {
    elem.classList.toggle('hidden', isStaff);
  });
  // Demo-only controls (sample logins, reset button) stay hidden on a live deployment
  document.querySelectorAll('.demo-only').forEach((elem) => {
    if (!siteInfo.demo_mode) elem.classList.add('hidden');
    else if (!elem.classList.contains('staff-only') || isStaff) elem.classList.remove('hidden');
  });
}

/* --------------------------------------------------------------------------
   2. View Routing & Top Button Visibility Control
   -------------------------------------------------------------------------- */

function switchView(targetViewKey) {
  activeView = targetViewKey;

  // Update Sidebar Active States
  document.querySelectorAll('.sidebar-nav .nav-item').forEach((button) => {
    button.classList.remove('active');
    button.removeAttribute('aria-current');
  });

  const activeNavButton = Array.from(document.querySelectorAll('.sidebar-nav .nav-item'))
    .find((btn) => btn.getAttribute('onclick')?.includes(`'${targetViewKey}'`));
  if (activeNavButton) {
    activeNavButton.classList.add('active');
    activeNavButton.setAttribute('aria-current', 'page');
  }

  // Toggle View Panels
  document.querySelectorAll('.view-panel').forEach((panel) => panel.classList.remove('active'));
  const targetPanel = document.getElementById(`view-${targetViewKey}`);
  if (targetPanel) targetPanel.classList.add('active');

  // Control Top-Right "Book Consultation" Button: ONLY shown on Dashboard & Consultations
  const topActionContainer = document.getElementById('top-quick-action-container');
  if (topActionContainer) {
    if (targetViewKey === 'dashboard' || targetViewKey === 'consultations') {
      topActionContainer.classList.remove('hidden');
    } else {
      topActionContainer.classList.add('hidden');
    }
  }

  const routeHeaders = {
    dashboard: ['Hospital Overview', 'Current clinical metrics & status'],
    beds: ['Hospital Ward Bed Map', 'Bed occupancy by ward'],
    employees: ['Medical Specialists & Doctors', 'Registry of clinical practitioners and specialists'],
    patients: [activeUser.role === 'staff' ? 'Patient Database' : 'My Medical Profile', 'Inpatient and outpatient clinical histories'],
    profile: ['My Medical Profile', 'Your health record, purchases and privacy controls'],
    privacy: ['Privacy Requests', 'Data deletion requests from patients and staff'],
    consultations: ['Consultation Appointments', 'Scheduled clinical appointments & status'],
    prescriptions: ['Digital Prescriptions & Rx Slip', 'Doctor diagnoses, dosage plans & printable slips'],
    pharmacy: ['Pharmacy Stock & Formulations', 'Inventory levels, rates & instant restock/purchase'],
    emt: ['Emergency Medical Fleet (EMT)', 'Ambulance readiness & emergency hotline']
  };

  if (routeHeaders[targetViewKey]) {
    document.getElementById('page-title').textContent = routeHeaders[targetViewKey][0];
    document.getElementById('page-subtitle').textContent = routeHeaders[targetViewKey][1];
  }

  if (targetViewKey === 'dashboard') refreshDashboard();
  if (targetViewKey === 'beds') loadWardBeds();
  if (targetViewKey === 'employees') loadDoctorsRegistry();
  if (targetViewKey === 'patients') loadPatientsRegistry();
  if (targetViewKey === 'consultations') loadConsultationsRegistry();
  if (targetViewKey === 'prescriptions') loadPrescriptionsRegistry();
  if (targetViewKey === 'pharmacy') loadPharmacyInventory();
  if (targetViewKey === 'emt') loadAmbulanceFleet();
  if (targetViewKey === 'profile') loadPatientProfile();
  if (targetViewKey === 'privacy') loadPrivacyRequests();
}

function openNewActionModal() {
  openModal('modal-add-consultation');
}

/* --------------------------------------------------------------------------
   3. Dashboard Overview Data
   -------------------------------------------------------------------------- */

async function refreshDashboard() {
  try {
    const statsResponse = await fetch('/api/dashboard/stats');
    const metrics = await statsResponse.json();

    document.getElementById('stat-consultations').textContent = metrics.scheduled_consultations || 0;
    document.getElementById('stat-available-beds').textContent = metrics.available_beds || 0;
    document.getElementById('stat-total-beds').textContent = metrics.total_beds || 0;
    document.getElementById('stat-patients').textContent = metrics.patients || 0;
    document.getElementById('stat-employees').textContent = metrics.employees || 0;
    document.getElementById('stat-ambulances').textContent = metrics.available_ambulances || 0;

    const consultationsResponse = await fetch('/api/consultations');
    const appointments = await consultationsResponse.json();
    const dashConTbody = document.getElementById('dash-consultations-tbody');
    dashConTbody.innerHTML = appointments.slice(0, 4).map((item) => `
      <tr>
        <td><strong>${escapeHtml(item.PATIENT_NAME)}</strong></td>
        <td>${escapeHtml(item.DOCTOR_NAME)}</td>
        <td>${escapeHtml(item.REASON)}</td>
        <td><span class="status-pill status-${item.STATUS.toLowerCase()}">${item.STATUS}</span></td>
      </tr>
    `).join('') || '<tr><td colspan="4" class="text-muted">No scheduled appointments.</td></tr>';

    const emtResponse = await fetch('/api/emt');
    const ambulances = await emtResponse.json();
    const dashEmtTbody = document.getElementById('dash-emt-tbody');
    dashEmtTbody.innerHTML = ambulances.slice(0, 4).map((amb) => `
      <tr>
        <td><strong>${escapeHtml(amb.VNO)}</strong></td>
        <td>${escapeHtml(amb.VTYPE)}</td>
        <td>${escapeHtml(amb.DRIVER_NAME)}</td>
        <td><span class="status-pill status-${amb.STATUS.toLowerCase()}">${amb.STATUS}</span></td>
      </tr>
    `).join('') || '<tr><td colspan="4">No ambulances found.</td></tr>';
  } catch (err) {
    console.error('Error loading dashboard statistics:', err);
  }
}

/* --------------------------------------------------------------------------
   4. Theatre-Style Hospital Ward Bed Map (70 Beds + Patient Booking)
   -------------------------------------------------------------------------- */

async function loadWardBeds() {
  try {
    const response = await fetch('/api/beds');
    hospitalBedsCache = await response.json();
    renderBedsMatrix(hospitalBedsCache);
  } catch (err) {
    notifyUser('Failed to load ward beds layout', 'error');
  }
}

function renderBedsMatrix(beds) {
  const container = document.getElementById('ward-sections-container');
  if (!container) return;

  const groupedWards = beds.reduce((acc, bed) => {
    acc[bed.WARD_TYPE] = acc[bed.WARD_TYPE] || [];
    acc[bed.WARD_TYPE].push(bed);
    return acc;
  }, {});

  const isStaff = activeUser && activeUser.role === 'staff';

  container.innerHTML = Object.keys(groupedWards).map((wardName) => {
    const wardBeds = groupedWards[wardName];
    const availableCount = wardBeds.filter((b) => b.STATUS === 'Available').length;

    return `
      <div class="ward-block glass-panel">
        <div class="ward-block-header">
          <h3><i class="fa-solid fa-hospital"></i> ${escapeHtml(wardName)}</h3>
          <span class="ward-badge">${availableCount} of ${wardBeds.length} Beds Available</span>
        </div>
        <div class="beds-grid-theatre">
          ${wardBeds.map((bed) => {
            const stateClass = `state-${bed.STATUS.toLowerCase()}`;
            const isOccupied = bed.STATUS === 'Occupied';
            const isAvailable = bed.STATUS === 'Available';

            // Patients never receive other patients' details from the API; only staff or the bed's own patient see them.
            const showPatient = isOccupied && (isStaff || bed.IS_MINE);
            const actionHint = isOccupied
              ? (isStaff ? 'Select to discharge' : '')
              : isAvailable ? (isStaff ? 'Select to allocate a patient' : 'Select to reserve') : '';
            const accessibleLabel = [
              `${bed.WARD_TYPE} ${bed.BED_NUMBER}`,
              bed.STATUS,
              showPatient ? `patient ${bed.PATIENT_NAME || ''}` : '',
              bed.IS_MINE ? 'your bed' : '',
              actionHint
            ].filter(Boolean).join(', ');

            return `
              <button type="button" class="bed-seat-card ${stateClass}" onclick="handleBedCardClick('${bed.BED_ID}')" aria-label="${escapeHtml(accessibleLabel)}" ${bed.STATUS === 'Maintenance' ? 'aria-disabled="true"' : ''}>
                <i class="fa-solid fa-bed" aria-hidden="true"></i>
                <span class="bed-number">${escapeHtml(bed.BED_NUMBER)}</span>
                <span class="bed-status-tag">${bed.IS_MINE ? 'Your bed' : bed.STATUS}</span>

                ${showPatient ? `
                  <span class="bed-tooltip" aria-hidden="true">
                    <span class="tt-title"><i class="fa-solid fa-user" aria-hidden="true"></i> ${escapeHtml(bed.PATIENT_NAME || 'Admitted Patient')}</span>
                    <span class="tt-line"><strong>Age/Gender:</strong> ${bed.PATIENT_AGE || '--'} yrs / ${escapeHtml(bed.PATIENT_GENDER || '--')}</span>
                    <span class="tt-line"><strong>Condition:</strong> ${escapeHtml(bed.PATIENT_ISSUE || 'Under observation')}</span>
                    <span class="tt-line"><strong>Admitted:</strong> ${escapeHtml(bed.ASSIGNED_DATE || 'Recent')}</span>
                    ${actionHint ? `<span class="tt-line" style="color: #38bdf8; font-size: 11px; margin-top: 4px; font-weight: bold;">${actionHint}</span>` : ''}
                  </span>
                ` : `
                  <span class="bed-tooltip" aria-hidden="true">
                    <span class="tt-title">${escapeHtml(bed.BED_NUMBER)}</span>
                    <span class="tt-line">${escapeHtml(bed.STATUS)}</span>
                    ${actionHint ? `<span class="tt-line" style="color: #38bdf8; font-size: 11px; margin-top: 4px; font-weight: bold;">${actionHint}</span>` : ''}
                  </span>
                `}
              </button>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }).join('');
}

async function handleBedCardClick(bedId) {
  const bed = hospitalBedsCache.find((b) => b.BED_ID === bedId);
  if (!bed) return;

  // Patient Bed Booking Flow
  if (activeUser.role === 'patient') {
    if (bed.STATUS === 'Available') {
      if (confirm(`Reserve ${bed.BED_NUMBER} in ${bed.WARD_TYPE}?\n\nNo payment is taken through this portal for reserving a bed. Ward charges, if any, are explained by the admissions desk before admission.`)) {
        try {
          const response = await fetch('/api/beds/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ BED_ID: bedId })
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || 'Failed to reserve bed');

          notifyUser(payload.message, 'success');
          loadWardBeds();
          refreshDashboard();
        } catch (err) {
          notifyUser(err.message, 'error');
        }
      }
    } else if (bed.STATUS === 'Occupied') {
      notifyUser(bed.IS_MINE ? `${bed.BED_NUMBER} is reserved for you.` : `${bed.BED_NUMBER} is currently occupied.`, 'info');
    } else {
      notifyUser(`Bed ${bed.BED_NUMBER} is undergoing maintenance.`, 'info');
    }
    return;
  }

  // Staff Bed Actions (Discharge or Allocate)
  if (bed.STATUS === 'Occupied') {
    if (confirm(`Discharge patient ${bed.PATIENT_NAME} from ${bed.BED_NUMBER} (${bed.WARD_TYPE})?`)) {
      const response = await fetch('/api/beds/vacate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ BED_ID: bedId })
      });
      const data = await response.json();
      if (response.ok) {
        notifyUser(data.message, 'success');
        loadWardBeds();
        refreshDashboard();
      } else {
        notifyUser(data.error, 'error');
      }
    }
  } else if (bed.STATUS === 'Available') {
    openModal('modal-assign-bed');
    setTimeout(() => {
      const bedDropdown = document.getElementById('bed-select-id');
      if (bedDropdown) bedDropdown.value = bedId;
    }, 150);
  }
}

async function handleAssignBed(event) {
  event.preventDefault();
  const bedId = document.getElementById('bed-select-id').value;
  const patientId = document.getElementById('bed-patient-id').value;

  try {
    const response = await fetch('/api/beds/assign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ BED_ID: bedId, PATIENT_ID: patientId })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Failed to allocate bed');

    notifyUser(payload.message, 'success');
    closeModal('modal-assign-bed');
    loadWardBeds();
    refreshDashboard();
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

/* --------------------------------------------------------------------------
   5. Pharmacy Stock & Patient Medicine Purchasing
   -------------------------------------------------------------------------- */

async function loadPharmacyInventory() {
  try {
    const response = await fetch('/api/pharmacy');
    pharmacyInventoryCache = await response.json();
    const tableBody = document.getElementById('pharmacy-tbody');
    const isStaff = activeUser && activeUser.role === 'staff';

    tableBody.innerHTML = pharmacyInventoryCache.map((med) => {
      const isAvailable = med.STOCK > 0;
      return `
        <tr>
          <td><strong>${escapeHtml(med.MEDICINE_NAME)}</strong></td>
          <td><span class="badge-role">${escapeHtml(med.MEDICINE_TYPE)}</span></td>
          <td>
            ${isStaff ? `
              <span style="color: ${med.STOCK < 50 ? '#f87171' : '#34d399'}; font-weight: 700;">
                ${med.STOCK} units ${med.STOCK < 50 ? '(Low)' : ''}
              </span>
            ` : `
              <span class="stock-badge-tag ${isAvailable ? 'stock-in' : 'stock-out'}">
                <i class="fa-solid ${isAvailable ? 'fa-circle-check' : 'fa-circle-xmark'}"></i>
                ${isAvailable ? 'Available' : 'Out of Stock'}
              </span>
            `}
          </td>
          <td>₹${Number(med.PRICE).toFixed(2)}</td>
          <td>
            ${isStaff ? `
              <button class="btn btn-sm btn-outline" onclick="promptStockUpdate('${escapeHtml(med.MEDICINE_NAME)}', ${med.STOCK})">
                <i class="fa-solid fa-boxes-stacked"></i> Update Stock
              </button>
            ` : `
              <button class="btn btn-sm btn-primary" onclick="openBuyMedicineModal('${escapeHtml(med.MEDICINE_NAME)}', ${med.PRICE}, ${med.STOCK})" ${!isAvailable ? 'disabled' : ''}>
                <i class="fa-solid fa-cart-plus"></i> Buy Medicine
              </button>
            `}
          </td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="5">Pharmacy catalog is empty.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load pharmacy catalog', 'error');
  }
}

let selectedMedPrice = 0;
let selectedMedStock = 0;

function openBuyMedicineModal(medicineName, price, stock) {
  selectedMedPrice = price;
  selectedMedStock = stock;

  document.getElementById('buy-med-name').value = medicineName;
  document.getElementById('buy-med-price').value = `₹${price.toFixed(2)}`;
  document.getElementById('buy-med-qty').value = 1;
  calculatePurchaseTotal();

  openModal('modal-buy-medicine');
}

function calculatePurchaseTotal() {
  const qtyInput = document.getElementById('buy-med-qty');
  const qty = parseInt(qtyInput.value, 10) || 1;

  if (qty > selectedMedStock) {
    notifyUser(`Warning: Requested quantity (${qty}) exceeds available stock (${selectedMedStock} units).`, 'error');
  }

  const total = qty * selectedMedPrice;
  document.getElementById('buy-med-total').textContent = `₹${total.toFixed(2)}`;
}

async function handleBuyMedicine(event) {
  event.preventDefault();
  const medName = document.getElementById('buy-med-name').value;
  const qty = parseInt(document.getElementById('buy-med-qty').value, 10);

  if (qty > selectedMedStock) {
    notifyUser(`Cannot proceed: Requested quantity (${qty}) exceeds available stock (${selectedMedStock} units).`, 'error');
    return;
  }

  try {
    const response = await fetch('/api/pharmacy/buy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ MEDICINE_NAME: medName, QUANTITY: qty })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Failed to complete medicine purchase');

    notifyUser(payload.message, 'success');
    closeModal('modal-buy-medicine');
    loadPharmacyInventory();
    refreshDashboard();
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

async function handleAddMedicine(event) {
  event.preventDefault();
  const medicinePayload = {
    MEDICINE_NAME: document.getElementById('med-name').value.trim(),
    MEDICINE_TYPE: document.getElementById('med-type').value,
    STOCK: parseInt(document.getElementById('med-stock').value, 10),
    PRICE: parseFloat(document.getElementById('med-price').value)
  };

  const response = await fetch('/api/pharmacy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(medicinePayload)
  });
  const data = await response.json();

  if (response.ok) {
    notifyUser(data.message, 'success');
    closeModal('modal-add-medicine');
    loadPharmacyInventory();
    refreshDashboard();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function promptStockUpdate(medicineName, currentStock) {
  const updatedUnits = prompt(`Update stock count for ${medicineName}:`, currentStock);
  if (updatedUnits !== null && !isNaN(updatedUnits)) {
    await fetch(`/api/pharmacy/${encodeURIComponent(medicineName)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ STOCK: parseInt(updatedUnits, 10) })
    });
    notifyUser(`Stock updated for ${medicineName}`, 'success');
    loadPharmacyInventory();
  }
}

/* --------------------------------------------------------------------------
   6. Doctors & Medical Staff Registry (10 Doctors)
   -------------------------------------------------------------------------- */

async function loadDoctorsRegistry() {
  try {
    const response = await fetch('/api/employees');
    const doctorsList = await response.json();
    const tableBody = document.getElementById('employees-tbody');

    tableBody.innerHTML = doctorsList.map((doc) => `
      <tr>
        <td><code>${escapeHtml(doc.EID)}</code></td>
        <td><strong>${escapeHtml(doc.NAME)}</strong></td>
        <td><span class="badge-role">${escapeHtml(doc.DEPARTMENT)}</span></td>
        <td>${doc.AGE} yrs / ${escapeHtml(doc.GENDER)}</td>
        <td>₹${Number(doc.SALARY).toLocaleString()}</td>
        <td><a href="tel:${doc.MOBILE_NO}" style="color: #38bdf8; text-decoration: none;"><i class="fa-solid fa-phone"></i> ${escapeHtml(doc.MOBILE_NO || 'N/A')}</a></td>
        <td>
          <button class="btn-danger-sm" onclick="deleteDoctorRecord('${doc.EID}')" title="Delete doctor record" aria-label="Delete ${escapeHtml(doc.NAME)}">
            <i class="fa-solid fa-trash" aria-hidden="true"></i>
          </button>
        </td>
      </tr>
    `).join('') || '<tr><td colspan="7">No medical staff found.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load doctors list', 'error');
  }
}

async function handleAddEmployee(event) {
  event.preventDefault();
  const doctorPayload = {
    EID: document.getElementById('emp-eid').value.trim(),
    NAME: document.getElementById('emp-name').value.trim(),
    DEPARTMENT: document.getElementById('emp-dept').value.trim(),
    MOBILE_NO: document.getElementById('emp-mobile').value.trim(),
    AGE: parseInt(document.getElementById('emp-age').value, 10),
    GENDER: document.getElementById('emp-gender').value,
    SALARY: parseFloat(document.getElementById('emp-salary').value)
  };

  const response = await fetch('/api/employees', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doctorPayload)
  });
  const data = await response.json();

  if (response.ok) {
    notifyUser(data.message, 'success');
    closeModal('modal-add-employee');
    loadDoctorsRegistry();
    refreshDashboard();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function deleteDoctorRecord(eid) {
  if (confirm(`Remove doctor/staff record for ${eid}?`)) {
    const response = await fetch(`/api/employees/${eid}`, { method: 'DELETE' });
    const data = await response.json();
    if (response.ok) {
      notifyUser(data.message, 'success');
      loadDoctorsRegistry();
      refreshDashboard();
    } else {
      notifyUser(data.error, 'error');
    }
  }
}

/* --------------------------------------------------------------------------
   7. Patients Database (20 Patients)
   -------------------------------------------------------------------------- */

async function loadPatientsRegistry() {
  try {
    const response = await fetch('/api/patients');
    const patientsList = await response.json();
    const tableBody = document.getElementById('patients-tbody');
    const isStaff = activeUser && activeUser.role === 'staff';

    tableBody.innerHTML = patientsList.map((pat) => `
      <tr>
        <td><code>${escapeHtml(pat.PID)}</code></td>
        <td><strong>${escapeHtml(pat.NAME)}</strong></td>
        <td>${escapeHtml(pat.ISSUE || 'General Checkup')}<br /><small class="text-muted">${escapeHtml(pat.MEDICAL_HISTORY || '')}</small></td>
        <td>${escapeHtml(pat.BLOOD_GROUP || '--')} / ${escapeHtml(pat.ALLERGIES || '--')}</td>
        <td>${pat.AGE || '--'} / ${escapeHtml(pat.GENDER || '--')}${pat.GUARDIAN_NAME ? `<br /><small class="text-muted">Guardian: ${escapeHtml(pat.GUARDIAN_NAME)}</small>` : ''}</td>
        <td>${pat.BED_NUMBER ? `${escapeHtml(pat.BED_NUMBER)} <small class="text-muted">(${escapeHtml(pat.WARD_TYPE)})</small>` : '--'}</td>
        <td><a href="tel:${escapeHtml(pat.MOBILE_NO)}" style="color: #38bdf8; text-decoration: none;"><i class="fa-solid fa-phone" aria-hidden="true"></i> ${escapeHtml(pat.MOBILE_NO || 'N/A')}</a></td>
        <td><span class="badge-role">${escapeHtml(pat.BILL_NO || 'N/A')}</span></td>
        ${isStaff ? `
          <td>
            <button class="btn-danger-sm" onclick="deletePatientRecord('${pat.PID}')" title="Delete record" aria-label="Delete patient ${escapeHtml(pat.NAME)}">
              <i class="fa-solid fa-trash" aria-hidden="true"></i>
            </button>
          </td>
        ` : ''}
      </tr>
    `).join('') || '<tr><td colspan="9">No patient records available.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load patient database', 'error');
  }
}

async function handleAddPatient(event) {
  event.preventDefault();
  const patientPayload = {
    NAME: document.getElementById('pat-name').value.trim(),
    ISSUE: document.getElementById('pat-issue').value.trim(),
    AGE: parseInt(document.getElementById('pat-age').value, 10),
    GENDER: document.getElementById('pat-gender').value,
    FEES: parseFloat(document.getElementById('pat-fees').value),
    MOBILE_NO: document.getElementById('pat-mobile').value.trim(),
    GUARDIAN_NAME: document.getElementById('pat-guardian').value.trim()
  };

  const response = await fetch('/api/patients', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patientPayload)
  });
  const data = await response.json();

  if (response.ok) {
    notifyUser(data.message, 'success');
    closeModal('modal-add-patient');
    loadPatientsRegistry();
    refreshDashboard();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function deletePatientRecord(pid) {
  if (confirm(`Are you sure you want to delete patient ${pid}?`)) {
    const response = await fetch(`/api/patients/${pid}`, { method: 'DELETE' });
    const data = await response.json();
    if (response.ok) {
      notifyUser(data.message, 'success');
      loadPatientsRegistry();
      refreshDashboard();
    } else {
      notifyUser(data.error, 'error');
    }
  }
}

/* --------------------------------------------------------------------------
   8. Consultations & Prescribe Flow
   -------------------------------------------------------------------------- */

async function loadConsultationsRegistry() {
  try {
    const response = await fetch('/api/consultations');
    const consultations = await response.json();
    const tableBody = document.getElementById('consultations-tbody');
    const isStaff = activeUser && activeUser.role === 'staff';

    tableBody.innerHTML = consultations.map((item) => `
      <tr>
        <td><code>${escapeHtml(item.CONSULTATION_ID)}</code></td>
        <td><strong>${escapeHtml(item.PATIENT_NAME)}</strong></td>
        <td>${escapeHtml(item.DOCTOR_NAME)} <small style="color: #94a3b8;">(${escapeHtml(item.DEPARTMENT)})</small></td>
        <td>${escapeHtml(item.REASON)}</td>
        <td>₹${Number(item.FEES || 0).toLocaleString()}</td>
        <td>${escapeHtml(item.TIME)}</td>
        <td><span class="status-pill status-${item.STATUS.toLowerCase()}">${item.STATUS}</span></td>
        ${isStaff ? `
          <td>
            ${item.STATUS === 'Scheduled' ? `
              <button class="btn btn-sm btn-primary" onclick="preparePrescriptionFor('${item.CONSULTATION_ID}')">
                <i class="fa-solid fa-file-prescription"></i> Prescribe
              </button>
            ` : '<small class="text-muted"><i class="fa-solid fa-check"></i> Completed</small>'}
          </td>
        ` : ''}
      </tr>
    `).join('') || '<tr><td colspan="8">No consultations scheduled.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load consultations list', 'error');
  }
}

async function handleBookConsultation(event) {
  event.preventDefault();
  const appointmentPayload = {
    PATIENT_ID: document.getElementById('con-patient-id')?.value,
    EMP_ID: document.getElementById('con-doctor-id').value,
    REASON: document.getElementById('con-reason').value.trim(),
    FEES: parseFloat(document.getElementById('con-fee').value),
    TIME: document.getElementById('con-time').value.replace('T', ' ')
  };

  const response = await fetch('/api/consultations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(appointmentPayload)
  });
  const data = await response.json();

  if (response.ok) {
    notifyUser(data.message, 'success');
    closeModal('modal-add-consultation');
    loadConsultationsRegistry();
    refreshDashboard();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function preparePrescriptionFor(consultationId) {
  try {
    const response = await fetch(`/api/consultations/${consultationId}`);
    const consultationData = await response.json();
    if (!response.ok) throw new Error(consultationData.error || 'Failed to fetch consultation details');

    openModal('modal-add-prescription');

    setTimeout(() => {
      const rxDropdown = document.getElementById('rx-consultation-id');
      if (rxDropdown) {
        rxDropdown.innerHTML = `<option value="${consultationData.CONSULTATION_ID}" selected>${consultationData.CONSULTATION_ID} - ${consultationData.PATIENT_NAME} (Dr. ${consultationData.DOCTOR_NAME})</option>`;
      }
      document.getElementById('rx-diagnosis').value = consultationData.REASON || '';
    }, 150);
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

function addMedicineRow() {
  const container = document.getElementById('rx-meds-container');
  const row = document.createElement('div');
  row.className = 'medicine-row';
  row.innerHTML = `
    <input type="text" placeholder="Medicine Name (e.g. Paracetamol 650mg)" class="rx-med-name" aria-label="Medicine name" required />
    <input type="text" placeholder="Dosage (e.g. 1 Tablet)" class="rx-med-dosage" aria-label="Dosage" value="1 Tablet" />
    <input type="text" placeholder="Frequency (e.g. Twice daily)" class="rx-med-freq" aria-label="Frequency" value="Twice daily after meals" />
    <button type="button" class="btn-danger-sm" onclick="this.parentElement.remove()" title="Remove" aria-label="Remove medicine row"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>
  `;
  container.appendChild(row);
}

async function handleCreatePrescription(event) {
  event.preventDefault();
  const medicineRows = document.querySelectorAll('.medicine-row');
  const medicinesList = [];

  medicineRows.forEach((row) => {
    const medName = row.querySelector('.rx-med-name').value.trim();
    if (medName) {
      medicinesList.push({
        name: medName,
        dosage: row.querySelector('.rx-med-dosage').value.trim(),
        frequency: row.querySelector('.rx-med-freq').value.trim(),
        duration: '5 Days'
      });
    }
  });

  const prescriptionPayload = {
    CONSULTATION_ID: document.getElementById('rx-consultation-id').value,
    DIAGNOSIS: document.getElementById('rx-diagnosis').value.trim(),
    INSTRUCTIONS: document.getElementById('rx-instructions').value.trim(),
    MEDICINES: medicinesList
  };

  try {
    const response = await fetch('/api/prescriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prescriptionPayload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Failed to issue prescription');

    notifyUser(data.message, 'success');
    closeModal('modal-add-prescription');
    switchView('prescriptions');
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

/* --------------------------------------------------------------------------
   9. Prescriptions List & Download/Print Rx Slip
   -------------------------------------------------------------------------- */

async function loadPrescriptionsRegistry() {
  try {
    const response = await fetch('/api/prescriptions');
    const prescriptions = await response.json();
    const container = document.getElementById('prescriptions-container');

    container.innerHTML = prescriptions.map((rx) => `
      <div class="prescription-card">
        <div>
          <div class="rx-head">
            <span class="rx-num"><i class="fa-solid fa-file-waveform"></i> ${escapeHtml(rx.PRESCRIPTION_ID)}</span>
            <span class="rx-date"><i class="fa-solid fa-calendar"></i> ${escapeHtml(rx.DATE)}</span>
          </div>
          <div class="rx-patient">${escapeHtml(rx.PATIENT_NAME)}</div>
          <small class="text-muted"><i class="fa-solid fa-user-doctor"></i> Prescribed by ${escapeHtml(rx.DOCTOR_NAME)} (${escapeHtml(rx.DEPARTMENT)})</small>
          <div class="rx-diag"><strong>Diagnosis:</strong> ${escapeHtml(rx.DIAGNOSIS)}</div>
          ${rx.INSTRUCTIONS ? `<div class="rx-diag"><strong>Instructions:</strong> ${escapeHtml(rx.INSTRUCTIONS)}</div>` : ''}
          <div class="rx-meds-list">
            ${rx.medicines.map((m) => `
              <div class="rx-med-item">
                <span><strong>${escapeHtml(m.MEDICINE_NAME)}</strong> (${escapeHtml(m.DOSAGE)})</span>
                <span>${escapeHtml(m.FREQUENCY)}</span>
              </div>
            `).join('')}
          </div>
        </div>
        <button class="btn btn-sm btn-outline btn-block" onclick="openPrescriptionSlip('${rx.PRESCRIPTION_ID}')" style="margin-top: 10px;">
          <i class="fa-solid fa-download"></i> Download / Print Rx Slip
        </button>
      </div>
    `).join('') || '<p class="text-muted">No prescriptions issued yet.</p>';
  } catch (err) {
    notifyUser('Failed to load prescriptions', 'error');
  }
}

async function openPrescriptionSlip(prescriptionId) {
  try {
    const response = await fetch(`/api/prescriptions/${prescriptionId}`);
    const rx = await response.json();
    if (!response.ok) throw new Error(rx.error || 'Failed to fetch prescription slip');

    const container = document.getElementById('printable-rx-content');
    container.innerHTML = `
      <div class="prescription-slip">
        <div class="slip-header">
          <div>
            <div class="slip-hospital-title">${escapeHtml(siteInfo.business.trading_name)}</div>
            <p style="font-size: 12px; color: #475569;">${escapeHtml(siteInfo.business.name)}, ${escapeHtml(siteInfo.business.address)}</p>
            <p style="font-size: 11px; color: #475569;">Reg. ${escapeHtml(siteInfo.business.registration)} | ${escapeHtml(siteInfo.business.phone)} | ${escapeHtml(siteInfo.business.email)}</p>
          </div>
          <div style="text-align: right;">
            <span style="font-size: 18px; font-weight: 800; color: #0284c7;">℞ PRESCRIPTION</span>
            <p style="font-size: 12px; font-weight: 700;">ID: ${escapeHtml(rx.PRESCRIPTION_ID)}</p>
            <p style="font-size: 12px;">Date: ${escapeHtml(rx.DATE)}</p>
          </div>
        </div>

        <div class="slip-patient-info">
          <div>
            <p><strong>Patient Name:</strong> ${escapeHtml(rx.PATIENT_NAME)} (PID: ${escapeHtml(rx.PATIENT_ID)})</p>
            <p><strong>Age / Gender:</strong> ${rx.PATIENT_AGE || '--'} yrs / ${escapeHtml(rx.PATIENT_GENDER || '--')}</p>
            <p><strong>Emergency Mobile:</strong> ${escapeHtml(rx.PATIENT_MOBILE || 'N/A')}</p>
          </div>
          <div>
            <p><strong>Attending Doctor:</strong> ${escapeHtml(rx.DOCTOR_NAME)}</p>
            <p><strong>Department:</strong> ${escapeHtml(rx.DEPARTMENT)}</p>
            <p><strong>Consultation Ref:</strong> ${escapeHtml(rx.CONSULTATION_ID)}</p>
          </div>
        </div>

        <div style="margin: 14px 0;">
          <p><strong>Primary Diagnosis:</strong> <span style="color: #0f172a; font-weight: 700;">${escapeHtml(rx.DIAGNOSIS)}</span></p>
          ${rx.INSTRUCTIONS ? `<p style="margin-top: 4px;"><strong>Clinical Advice & Diet:</strong> ${escapeHtml(rx.INSTRUCTIONS)}</p>` : ''}
        </div>

        <table class="slip-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Prescribed Medicine</th>
              <th>Dosage</th>
              <th>Frequency</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            ${rx.medicines.map((m, idx) => `
              <tr>
                <td>${idx + 1}</td>
                <td><strong>${escapeHtml(m.MEDICINE_NAME)}</strong></td>
                <td>${escapeHtml(m.DOSAGE)}</td>
                <td>${escapeHtml(m.FREQUENCY)}</td>
                <td>${escapeHtml(m.DURATION)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>

        <div class="slip-footer">
          <p style="font-size: 11px; color: #475569;">Generated electronically from the ${escapeHtml(siteInfo.business.trading_name)} records system. Not valid without the prescribing doctor's signature.</p>
          <div class="slip-sign-line">
            Dr. ${escapeHtml(rx.DOCTOR_NAME)}<br>
            <span style="font-size: 10px; font-weight: normal;">Authorized Medical Officer</span>
          </div>
        </div>
      </div>
    `;

    openModal('modal-download-prescription');
  } catch (err) {
    notifyUser(err.message, 'error');
  }
}

/* --------------------------------------------------------------------------
   10. Emergency Ambulance Fleet
   -------------------------------------------------------------------------- */

async function loadAmbulanceFleet() {
  try {
    const response = await fetch('/api/emt');
    const fleet = await response.json();
    const tableBody = document.getElementById('emt-tbody');
    const isStaff = activeUser && activeUser.role === 'staff';

    tableBody.innerHTML = fleet.map((amb) => `
      <tr>
        <td><code>${escapeHtml(amb.VNO)}</code></td>
        <td><strong>${escapeHtml(amb.VTYPE)}</strong></td>
        <td>${escapeHtml(amb.DRIVER_NAME)}</td>
        <td><a href="tel:${escapeHtml(amb.MOBILE_NO)}" style="color: #38bdf8; text-decoration: none;"><i class="fa-solid fa-phone" aria-hidden="true"></i> ${escapeHtml(amb.MOBILE_NO)}</a></td>
        <td><span class="status-pill status-${amb.STATUS.toLowerCase()}">${amb.STATUS}</span></td>
        ${isStaff ? `
          <td>
            <select aria-label="Change status of ${escapeHtml(amb.VNO)}" onchange="updateAmbulanceStatus('${amb.VNO}', this.value)" style="padding: 4px 8px; border-radius: 6px; background: rgba(0,0,0,0.5); color: #fff; border: 1px solid var(--border-color);">
              <option value="Available" ${amb.STATUS === 'Available' ? 'selected' : ''}>Available</option>
              <option value="Dispatched" ${amb.STATUS === 'Dispatched' ? 'selected' : ''}>Dispatched</option>
              <option value="Maintenance" ${amb.STATUS === 'Maintenance' ? 'selected' : ''}>Maintenance</option>
            </select>
          </td>
        ` : ''}
      </tr>
    `).join('') || '<tr><td colspan="6">No ambulances registered.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load EMT fleet', 'error');
  }
}

async function handleAddEmt(event) {
  event.preventDefault();
  const ambulancePayload = {
    VNO: document.getElementById('emt-vno').value.trim(),
    VTYPE: document.getElementById('emt-vtype').value,
    DRIVER_NAME: document.getElementById('emt-driver').value.trim(),
    MOBILE_NO: document.getElementById('emt-mobile').value.trim(),
    STATUS: 'Available'
  };

  const response = await fetch('/api/emt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ambulancePayload)
  });
  const data = await response.json();

  if (response.ok) {
    notifyUser(data.message, 'success');
    closeModal('modal-add-emt');
    loadAmbulanceFleet();
    refreshDashboard();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function updateAmbulanceStatus(vehicleNo, newStatus) {
  try {
    const response = await fetch(`/api/emt/${vehicleNo}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ STATUS: newStatus })
    });
    if (response.ok) {
      notifyUser(`Ambulance ${vehicleNo} marked as ${newStatus}`, 'success');
      refreshDashboard();
    }
  } catch (err) {
    notifyUser('Failed to update ambulance status', 'error');
  }
}

/* --------------------------------------------------------------------------
   11. Modal Selectors & Helpers
   -------------------------------------------------------------------------- */

let modalReturnFocus = null;

function openModal(modalId) {
  modalReturnFocus = document.activeElement;
  if (modalId === 'modal-add-consultation') {
    populateConsultationSelectors();
  }
  if (modalId === 'modal-add-prescription') {
    populatePrescriptionConsultations();
    const medsContainer = document.getElementById('rx-meds-container');
    if (medsContainer) medsContainer.innerHTML = '';
    addMedicineRow();
  }
  if (modalId === 'modal-assign-bed') {
    populateBedAllocationSelectors();
  }
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('hidden');
  // Move keyboard focus into the dialog (after async selectors have rendered)
  setTimeout(() => {
    const focusables = getFocusable(modal);
    const firstField = focusables.find((el) => !el.classList.contains('btn-close')) || focusables[0];
    if (firstField) firstField.focus();
  }, 200);
}

function closeModal(modalId) {
  document.getElementById(modalId)?.classList.add('hidden');
  if (modalReturnFocus && document.body.contains(modalReturnFocus)) modalReturnFocus.focus();
  modalReturnFocus = null;
}

function getFocusable(container) {
  return Array.from(container.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )).filter((el) => el.offsetParent !== null);
}

// Escape closes the open dialog; Tab stays inside it
document.addEventListener('keydown', (event) => {
  const openDialog = Array.from(document.querySelectorAll('.modal-backdrop')).find((m) => !m.classList.contains('hidden'));
  if (!openDialog) return;
  if (event.key === 'Escape') {
    closeModal(openDialog.id);
    return;
  }
  if (event.key === 'Tab') {
    const focusables = getFocusable(openDialog);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});

async function populateConsultationSelectors() {
  const patientSelect = document.getElementById('con-patient-id');
  const doctorSelect = document.getElementById('con-doctor-id');

  if (patientSelect) {
    const pResponse = await fetch('/api/patients');
    const patients = await pResponse.json();
    patientSelect.innerHTML = patients.map((p) => `<option value="${p.PID}">${p.NAME} (${p.PID})</option>`).join('');
  }

  if (doctorSelect) {
    const dResponse = await fetch('/api/employees');
    const doctors = await dResponse.json();
    doctorSelect.innerHTML = doctors.map((d) => `<option value="${d.EID}">${d.NAME} - ${d.DEPARTMENT}</option>`).join('');
  }

  const defaultDateTime = new Date();
  defaultDateTime.setHours(defaultDateTime.getHours() + 1);
  defaultDateTime.setMinutes(0);
  document.getElementById('con-time').value = defaultDateTime.toISOString().slice(0, 16);
}

async function populatePrescriptionConsultations() {
  const rxSelect = document.getElementById('rx-consultation-id');
  const response = await fetch('/api/consultations');
  const list = await response.json();
  const scheduledList = list.filter((c) => c.STATUS === 'Scheduled');
  rxSelect.innerHTML = scheduledList.map((c) => `<option value="${c.CONSULTATION_ID}">${c.CONSULTATION_ID} - ${c.PATIENT_NAME} (Dr. ${c.DOCTOR_NAME})</option>`).join('') || '<option value="">No Active Consultations</option>';
}

async function populateBedAllocationSelectors() {
  const bedSelect = document.getElementById('bed-select-id');
  const patientSelect = document.getElementById('bed-patient-id');

  if (bedSelect) {
    const availableBeds = hospitalBedsCache.filter((b) => b.STATUS === 'Available');
    bedSelect.innerHTML = availableBeds.map((b) => `<option value="${b.BED_ID}">${b.BED_ID} - ${b.WARD_TYPE} (${b.BED_NUMBER})</option>`).join('') || '<option value="">No Available Beds</option>';
  }

  if (patientSelect) {
    const pResponse = await fetch('/api/patients');
    const patients = await pResponse.json();
    patientSelect.innerHTML = patients.map((p) => `<option value="${p.PID}">${p.NAME} (${p.PID}) - ${p.ISSUE || 'Patient'}</option>`).join('');
  }
}

async function resetDatabasePrompt() {
  if (confirm('Reset the database to the fictional demo data? All changes will be lost.')) {
    const response = await fetch('/api/admin/reset', { method: 'POST' });
    const payload = await response.json();
    notifyUser(payload.message, 'success');
    refreshDashboard();
    if (activeView === 'beds') loadWardBeds();
    if (activeView === 'employees') loadDoctorsRegistry();
    if (activeView === 'patients') loadPatientsRegistry();
    if (activeView === 'pharmacy') loadPharmacyInventory();
  }
}

function filterTable(tableId, query) {
  const filterVal = query.toLowerCase();
  const tableRows = document.querySelectorAll(`#${tableId} tbody tr`);
  tableRows.forEach((row) => {
    row.style.display = row.textContent.toLowerCase().includes(filterVal) ? '' : 'none';
  });
}

function filterPrescriptions(query) {
  const filterVal = query.toLowerCase();
  document.querySelectorAll('.prescription-card').forEach((card) => {
    card.style.display = card.textContent.toLowerCase().includes(filterVal) ? '' : 'none';
  });
}

function notifyUser(message, statusType = 'info') {
  const toastWrapper = document.getElementById('toast-container');
  if (!toastWrapper) return;
  const toastItem = document.createElement('div');
  toastItem.className = `toast toast-${statusType}`;
  toastItem.innerHTML = `<i class="fa-solid fa-circle-info" aria-hidden="true"></i> <span>${escapeHtml(message)}</span>`;
  toastWrapper.appendChild(toastItem);
  setTimeout(() => toastItem.remove(), 4000);
}

function escapeHtml(rawString) {
  if (!rawString) return '';
  return String(rawString)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* --------------------------------------------------------------------------
   12. Patient Profile, Privacy Controls & Data Deletion
   -------------------------------------------------------------------------- */

async function loadPatientProfile() {
  try {
    const response = await fetch('/api/patient/profile');
    const profile = await response.json();
    if (response.ok) {
      document.getElementById('profile-pid-badge').textContent = profile.PID;
      document.getElementById('prof-name').value = profile.NAME || '';
      document.getElementById('prof-mobile').value = profile.MOBILE_NO || '';
      document.getElementById('prof-age').value = profile.AGE ?? '';
      document.getElementById('prof-gender').value = profile.GENDER || 'Other';
      document.getElementById('prof-blood').value = profile.BLOOD_GROUP || 'Unknown';
      document.getElementById('prof-allergies').value = profile.ALLERGIES || '';
      document.getElementById('prof-issue').value = profile.ISSUE || '';
      document.getElementById('prof-history').value = profile.MEDICAL_HISTORY || '';
      document.getElementById('prof-bed-info').innerHTML = `<i class="fa-solid fa-bed" aria-hidden="true"></i> Bed: ${profile.BED_NUMBER ? `${escapeHtml(profile.BED_NUMBER)} (${escapeHtml(profile.WARD_TYPE)})` : 'Not currently admitted'}`;
      document.getElementById('prof-bill-info').textContent = `Bill No: ${profile.BILL_NO || 'N/A'}`;
    }

    const purchasesResponse = await fetch('/api/pharmacy/purchases');
    const purchases = await purchasesResponse.json();
    document.getElementById('profile-purchases-tbody').innerHTML = purchases.map((p) => `
      <tr>
        <td><code>${escapeHtml(p.PURCHASE_ID)}</code></td>
        <td>${escapeHtml(p.MEDICINE_NAME)}</td>
        <td>${p.QUANTITY}</td>
        <td>₹${Number(p.TOTAL_PRICE).toFixed(2)}</td>
        <td>${escapeHtml(p.PURCHASE_DATE)}</td>
      </tr>
    `).join('') || '<tr><td colspan="5" class="text-muted">No purchases yet.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load your profile', 'error');
  }

  document.getElementById('pref-marketing').checked = Boolean(activeUser && activeUser.marketing_opt_in);
  loadMyPrivacyRequests();
}

async function handleUpdateProfile(event) {
  event.preventDefault();
  const ageValue = document.getElementById('prof-age').value;
  const payload = {
    NAME: document.getElementById('prof-name').value.trim(),
    MOBILE_NO: document.getElementById('prof-mobile').value.trim(),
    AGE: ageValue === '' ? null : parseInt(ageValue, 10),
    GENDER: document.getElementById('prof-gender').value,
    BLOOD_GROUP: document.getElementById('prof-blood').value,
    ALLERGIES: document.getElementById('prof-allergies').value.trim(),
    ISSUE: document.getElementById('prof-issue').value.trim(),
    MEDICAL_HISTORY: document.getElementById('prof-history').value.trim()
  };
  const response = await fetch('/api/patient/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  notifyUser(response.ok ? data.message : data.error, response.ok ? 'success' : 'error');
  if (response.ok) {
    activeUser.name = payload.NAME;
    document.getElementById('display-user-name').textContent = payload.NAME;
  }
}

async function handleMarketingPreference(optIn) {
  const response = await fetch('/api/account/preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ marketing_opt_in: optIn })
  });
  const data = await response.json();
  if (response.ok) {
    activeUser.marketing_opt_in = data.marketing_opt_in;
    notifyUser(data.message, 'success');
  } else {
    notifyUser(data.error || 'Could not save preference', 'error');
  }
}

async function loadMyPrivacyRequests() {
  const container = document.getElementById('my-privacy-requests');
  if (!container) return;
  const response = await fetch('/api/privacy/deletion-request');
  const requests = response.ok ? await response.json() : [];
  container.innerHTML = requests.map((r) => `
    <p class="text-muted" style="font-size: 13px;">
      Deletion request #${r.ID} (${escapeHtml(r.CREATED_AT)}): <strong>${escapeHtml(r.STATUS)}</strong>
      ${r.RESOLUTION_NOTE ? ` &mdash; ${escapeHtml(r.RESOLUTION_NOTE)}` : ''}
    </p>
  `).join('');
}

async function handleDeletionRequest(event) {
  event.preventDefault();
  const response = await fetch('/api/privacy/deletion-request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      password: document.getElementById('delete-password').value,
      reason: document.getElementById('delete-reason').value.trim()
    })
  });
  const data = await response.json();
  if (response.ok) {
    notifyUser(data.message, 'success');
    document.getElementById('delete-password').value = '';
    closeModal('modal-delete-account');
    loadMyPrivacyRequests();
  } else {
    notifyUser(data.error, 'error');
  }
}

async function loadPrivacyRequests() {
  const tbody = document.getElementById('privacy-requests-tbody');
  try {
    const response = await fetch('/api/privacy/requests');
    const requests = await response.json();
    tbody.innerHTML = requests.map((r) => `
      <tr>
        <td>${r.ID}</td>
        <td>@${escapeHtml(r.USERNAME)}</td>
        <td>${escapeHtml(r.CREATED_AT)}</td>
        <td>${escapeHtml(r.REASON || '--')}</td>
        <td><span class="status-pill status-${r.STATUS === 'Pending' ? 'scheduled' : r.STATUS === 'Completed' ? 'completed' : 'dispatched'}">${escapeHtml(r.STATUS)}</span></td>
        <td>${escapeHtml(r.RESOLUTION_NOTE || '--')}${r.RESOLVED_BY ? `<br /><small class="text-muted">by @${escapeHtml(r.RESOLVED_BY)} on ${escapeHtml(r.RESOLVED_AT)}</small>` : ''}</td>
        <td>
          ${r.STATUS === 'Pending' ? `
            <button class="btn btn-sm btn-primary" onclick="resolvePrivacyRequest(${r.ID}, 'complete')">Erase data</button>
            <button class="btn btn-sm btn-outline" onclick="resolvePrivacyRequest(${r.ID}, 'reject')">Reject</button>
          ` : '--'}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="7" class="text-muted">No privacy requests.</td></tr>';
  } catch (err) {
    notifyUser('Failed to load privacy requests', 'error');
  }
}

async function resolvePrivacyRequest(requestId, action) {
  let body = {};
  if (action === 'complete') {
    if (!confirm('Erase this account and its non-clinical personal data? This cannot be undone.')) return;
  } else {
    const note = prompt('Reason for rejecting this request (shown to the requester):');
    if (!note) return;
    body = { note };
  }
  const response = await fetch(`/api/privacy/requests/${requestId}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  notifyUser(response.ok ? data.message : data.error, response.ok ? 'success' : 'error');
  loadPrivacyRequests();
}

/* --------------------------------------------------------------------------
   13. Cookie Consent
   Only a strictly necessary session cookie is used today. Any future analytics or
   marketing script must be loaded only when hasCookieConsent('analytics') is true.
   -------------------------------------------------------------------------- */

const COOKIE_CONSENT_KEY = 'pulsecare-cookie-consent';
const COOKIE_CONSENT_VERSION = 1;

function readCookieConsent() {
  try {
    const stored = JSON.parse(localStorage.getItem(COOKIE_CONSENT_KEY));
    return stored && stored.version === COOKIE_CONSENT_VERSION ? stored : null;
  } catch (err) {
    return null;
  }
}

function hasCookieConsent(category) {
  if (category === 'necessary') return true;
  const consent = readCookieConsent();
  return Boolean(consent && consent[category]);
}

function initCookieConsent() {
  if (!readCookieConsent()) {
    document.getElementById('cookie-banner').classList.remove('hidden');
  }
}

function toggleCookiePrefs() {
  const prefs = document.getElementById('cookie-prefs');
  const opening = prefs.classList.contains('hidden');
  prefs.classList.toggle('hidden', !opening);
  const manageBtn = document.getElementById('cookie-manage-btn');
  manageBtn.textContent = opening ? 'Save preferences' : 'Manage preferences';
  manageBtn.onclick = opening ? () => saveCookieConsent(document.getElementById('cookie-pref-analytics').checked) : toggleCookiePrefs;
}

function saveCookieConsent(allowAnalytics) {
  try {
    localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify({
      version: COOKIE_CONSENT_VERSION,
      necessary: true,
      analytics: Boolean(allowAnalytics),
      decided_at: new Date().toISOString()
    }));
  } catch (err) {
    // Storage blocked: the banner will simply be shown again next visit.
  }
  document.getElementById('cookie-banner').classList.add('hidden');
  notifyUser('Cookie preferences saved.', 'success');
}

function openCookieSettings() {
  const consent = readCookieConsent();
  document.getElementById('cookie-pref-analytics').checked = Boolean(consent && consent.analytics);
  document.getElementById('cookie-banner').classList.remove('hidden');
  const prefs = document.getElementById('cookie-prefs');
  if (prefs.classList.contains('hidden')) toggleCookiePrefs();
  document.getElementById('cookie-pref-analytics').focus();
}
