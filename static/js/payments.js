// static/js/payments.js — pricing modal + Stripe checkout

function showPricingModal() {
  const modal = document.getElementById('pricing-modal');
  if (modal) modal.style.display = 'flex';
}

function hidePricingModal() {
  const modal = document.getElementById('pricing-modal');
  if (modal) modal.style.display = 'none';
}

async function upgradePlan(priceType) {
  const token = localStorage.getItem('token');
  if (!token) {
    alert('Please log in first.');
    return;
  }

  try {
    const res = await fetch('/payments/create-checkout-session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ price_type: priceType })
    });

    const data = await res.json();

    if (data.url) {
      window.location.href = data.url;
      return;
    }

    alert(data.detail || data.message || 'Failed to start checkout');
  } catch (err) {
    console.error('upgradePlan error:', err);
    alert('Something went wrong. Please try again.');
  }
}

// Close modal when clicking the dark backdrop
document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('pricing-modal');
  if (!modal) return;

  modal.addEventListener('click', (e) => {
    if (e.target === modal) hidePricingModal();
  });
});
