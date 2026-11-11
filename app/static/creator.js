(() => {
  const grid = document.getElementById('calendar-grid');
  if (!grid) return;

  const selected = new Set();
  const slotInput = document.getElementById('slots-json');
  const counter = document.getElementById('selection-count');
  const weekLabel = document.getElementById('week-label');
  const locale = 'ca-ES';
  const pad = n => String(n).padStart(2, '0');
  const dateKey = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:00`;
  const mondayOf = value => {
    const date = new Date(value);
    date.setHours(0, 0, 0, 0);
    const day = date.getDay() || 7;
    date.setDate(date.getDate() - day + 1);
    return date;
  };
  let weekStart = mondayOf(new Date());

  function duration() {
    return Number(document.querySelector('input[name="duration"]:checked').value);
  }

  function overlaps(key, candidateDuration) {
    const start = new Date(key);
    const end = new Date(start.getTime() + candidateDuration * 60000);
    return [...selected].some(item => {
      if (item === key) return false;
      const otherStart = new Date(item);
      const otherEnd = new Date(otherStart.getTime() + duration() * 60000);
      return start < otherEnd && end > otherStart;
    });
  }

  function containingSelection(key) {
    const point = new Date(key);
    return [...selected].find(item => {
      const start = new Date(item);
      const end = new Date(start.getTime() + duration() * 60000);
      return point >= start && point < end;
    });
  }

  function sync() {
    const values = [...selected].sort();
    slotInput.value = JSON.stringify(values);
    counter.textContent = values.length;
  }

  function render() {
    grid.textContent = '';
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(weekStart);
      date.setDate(date.getDate() + index);
      return date;
    });
    const last = days[6];
    weekLabel.textContent = `${days[0].toLocaleDateString(locale, { day: 'numeric', month: 'long' })} – ${last.toLocaleDateString(locale, { day: 'numeric', month: 'long', year: 'numeric' })}`;

    const corner = document.createElement('div');
    corner.className = 'cal-corner';
    grid.appendChild(corner);
    days.forEach(day => {
      const header = document.createElement('div');
      header.className = 'cal-day';
      header.innerHTML = `${day.toLocaleDateString(locale, { weekday: 'short' })}<strong>${day.getDate()}</strong>`;
      grid.appendChild(header);
    });

    const now = new Date();
    for (let hour = 8; hour <= 20; hour++) {
      for (const minutes of [0, 30]) {
        if (hour === 20 && minutes === 30) continue;
        const time = document.createElement('div');
        time.className = 'cal-time';
        time.textContent = `${pad(hour)}:${pad(minutes)}`;
        grid.appendChild(time);
        days.forEach(day => {
          const start = new Date(day);
          start.setHours(hour, minutes, 0, 0);
          const key = dateKey(start);
          const cell = document.createElement('button');
          cell.type = 'button';
          cell.className = 'cal-cell';
          cell.dataset.key = key;
          cell.setAttribute('aria-label', start.toLocaleString(locale));
          if (start < now) cell.classList.add('past');
          const selectedOwner = containingSelection(key);
          if (selectedOwner) {
            cell.classList.add('selected');
            if (selectedOwner !== key) cell.classList.add('selected-continuation');
            cell.setAttribute('aria-pressed', 'true');
          } else {
            cell.setAttribute('aria-pressed', 'false');
          }
          cell.addEventListener('click', () => {
            if (cell.classList.contains('past')) return;
            const owner = containingSelection(key);
            if (owner) selected.delete(owner);
            else {
              const endHour = hour * 60 + minutes + duration();
              if (endHour > 21 * 60) return;
              if (overlaps(key, duration())) return;
              selected.add(key);
            }
            sync();
            render();
          });
          grid.appendChild(cell);
        });
      }
    }
  }

  document.getElementById('prev-week').addEventListener('click', () => { weekStart.setDate(weekStart.getDate() - 7); render(); });
  document.getElementById('next-week').addEventListener('click', () => { weekStart.setDate(weekStart.getDate() + 7); render(); });
  document.getElementById('today').addEventListener('click', () => { weekStart = mondayOf(new Date()); render(); });
  document.getElementById('clear-slots').addEventListener('click', () => { selected.clear(); sync(); render(); });
  document.querySelectorAll('input[name="duration"]').forEach(input => input.addEventListener('change', () => { selected.clear(); sync(); render(); }));
  document.getElementById('poll-form').addEventListener('submit', event => {
    sync();
    if (!selected.size) {
      event.preventDefault();
      alert('Selecciona almenys una opció horària al calendari.');
    }
  });
  render();
  sync();
})();
