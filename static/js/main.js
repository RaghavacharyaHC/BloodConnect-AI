/**
 * BloodConnect — Client-side Vanilla JavaScript
 * Keeps functionality simple, clean, and accessible for first-year students.
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Mobile Navigation Toggle
    const navToggle = document.getElementById('navToggle');
    const navMenu = document.getElementById('navMenu');

    if (navToggle && navMenu) {
        navToggle.addEventListener('click', () => {
            const isExpanded = navToggle.getAttribute('aria-expanded') === 'true';
            navToggle.setAttribute('aria-expanded', !isExpanded);
            navMenu.classList.toggle('show');
        });

        // Close mobile menu when a navigation link is clicked
        const navLinks = navMenu.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                navMenu.classList.remove('show');
                navToggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // 2. City Chips Quick Fill in Blood Search Form
    const cityChips = document.querySelectorAll('.city-chip');
    const cityInput = document.getElementById('city');

    if (cityChips.length > 0 && cityInput) {
        cityChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const selectedCity = chip.getAttribute('data-city');
                if (selectedCity) {
                    cityInput.value = selectedCity;
                    cityInput.focus();
                }
            });
        });
    }

    // 3. Search Form Basic Client-Side Validation
    const bloodSearchForm = document.getElementById('bloodSearchForm');
    if (bloodSearchForm) {
        bloodSearchForm.addEventListener('submit', (e) => {
            const bloodGroup = document.getElementById('blood_group');
            const unitsInput = document.getElementById('units');

            if (bloodGroup && !bloodGroup.value) {
                e.preventDefault();
                alert('Please select a blood group to search for availability.');
                bloodGroup.focus();
                return;
            }

            if (unitsInput && (parseInt(unitsInput.value, 10) < 1 || isNaN(parseInt(unitsInput.value, 10)))) {
                e.preventDefault();
                alert('Please enter at least 1 unit of blood.');
                unitsInput.focus();
                return;
            }
        });
    }
});
