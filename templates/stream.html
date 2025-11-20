<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ stream.title }} - Live</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body {
            background-color: #000; 
            font-family: 'Inter', sans-serif;
        }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #1f2937; }
        ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 4px; }
        .tip-animation { animation: slideIn 0.5s ease-out; }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        #video-container img { width: 100%; height: 100%; object-fit: contain; }
    </style>
</head>
<body class="text-white h-screen flex flex-col overflow-hidden">

    <!-- Flash Messages per Conferma Pagamento -->
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="absolute top-16 left-1/2 transform -translate-x-1/2 z-50 w-full max-w-md px-4">
            {% for category, message in messages %}
                <div class="p-4 rounded-lg shadow-2xl mb-4 text-center border backdrop-blur-md
                    {% if category == 'success' %} bg-green-900/80 border-green-500/50 text-white font-bold
                    {% else %} bg-gray-800/90 border-gray-500/50 text-white {% endif %}">
                    {{ message }}
                </div>
            {% endfor %}
            </div>
        {% endif %}
    {% endwith %}

    <!-- Navbar -->
    <nav class="bg-gray-900 border-b border-gray-800 p-3 flex justify-between items-center h-14 shrink-0 z-20">
        <a href="/" class="flex items-center gap-2 text-gray-400 hover:text-white transition">
            <i class="fas fa-arrow-left"></i> <span class="font-bold text-sm">Torna alla Hall</span>
        </a>
        <div class="font-bold text-gray-200 tracking-wide text-lg">{{ stream.title }}</div>
        <div class="w-24 text-right">
            {% if is_live %}
                <span class="bg-red-600 text-white text-xs px-2 py-1 rounded animate-pulse">LIVE</span>
            {% endif %}
        </div>
    </nav>

    <div class="flex flex-1 overflow-hidden">
        <!-- Video Area -->
        <main class="flex-1 flex flex-col bg-black relative">
            <div id="video-container" class="relative w-full h-full flex items-center justify-center bg-gray-900">
                {% if is_live %}
                    <img src="{{ url_for('video_feed') }}" alt="Live Stream">
                {% else %}
                    <div class="text-center p-10">
                        <i class="fas fa-moon text-6xl text-gray-700 mb-4"></i>
                        <p class="text-gray-400 text-xl">Il museo è chiuso al momento.</p>
                        <p class="text-gray-600 text-sm mt-2">La diretta è terminata o non è ancora iniziata.</p>
                        
                        <form action="/toggle_stream" method="POST" class="mt-6">
                            <button type="submit" class="bg-gray-800 hover:bg-gray-700 text-gray-400 px-4 py-2 rounded text-sm transition border border-gray-700">
                                (Admin) Avvia Test Cam
                            </button>
                        </form>
                    </div>
                {% endif %}
                <div id="tip-overlay" class="absolute top-10 right-10 w-80 z-50 pointer-events-none"></div>
            </div>
        </main>

        <!-- Chat -->
        <aside class="w-80 bg-gray-900 border-l border-gray-800 flex flex-col shrink-0 z-10">
            <div class="p-3 border-b border-gray-800 font-bold text-gray-400 text-xs uppercase tracking-widest text-center">Chat del Museo</div>
            <div id="chat-box" class="flex-1 overflow-y-auto p-4 space-y-2 text-sm"></div>
            
            <div class="p-3 bg-gray-800">
                <form id="chat-form" class="flex gap-2">
                    <input type="text" id="message-input" placeholder="Commenta..." class="w-full bg-gray-900 text-white rounded px-3 py-2 focus:outline-none border border-gray-700 focus:border-gray-500 transition text-sm">
                    <button type="submit" class="text-gray-400 hover:text-white px-2"><i class="fas fa-paper-plane"></i></button>
                </form>
            </div>

            <div class="p-4 border-t border-gray-800 bg-gray-900">
                <h3 class="text-gray-500 font-bold mb-3 text-center text-xs uppercase">Sostieni il restauro</h3>
                <div class="grid grid-cols-3 gap-2">
                    <button onclick="startPayment(2)" class="bg-gray-800 hover:bg-gray-100 hover:text-gray-900 text-gray-300 font-bold py-2 rounded border border-gray-700 transition text-xs shadow-sm">2€</button>
                    <button onclick="startPayment(5)" class="bg-gray-800 hover:bg-gray-100 hover:text-gray-900 text-gray-300 font-bold py-2 rounded border border-gray-700 transition text-xs shadow-sm">5€</button>
                    <button onclick="startPayment(10)" class="bg-gray-800 hover:bg-gray-100 hover:text-gray-900 text-gray-300 font-bold py-2 rounded border border-gray-700 transition text-xs shadow-sm">10€</button>
                </div>
            </div>
        </aside>
    </div>

    <script>
        const socket = io();
        const chatBox = document.getElementById('chat-box');
        
        // ID dello stream corrente (passato da Flask)
        const streamId = {{ stream.id }};

        // --- FUNZIONE DI PAGAMENTO STRIPE ---
        async function startPayment(amount) {
            try {
                const response = await fetch('/create-checkout-session', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ amount: amount, stream_id: streamId })
                });
                
                const data = await response.json();
                if (data.url) {
                    // Reindirizza l'utente alla pagina di pagamento Stripe
                    window.location.href = data.url;
                } else {
                    alert("Errore creazione pagamento: " + (data.error || 'Sconosciuto'));
                }
            } catch (error) {
                console.error("Errore fetch:", error);
                alert("Errore di connessione al server pagamenti.");
            }
        }

        socket.on('new_message', (data) => {
            const div = document.createElement('div');
            div.innerHTML = `<span class="font-bold text-gray-400">${data.username}:</span> <span class="text-gray-300">${data.message}</span>`;
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
        });

        socket.on('new_tip', (data) => {
            const div = document.createElement('div');
            div.className = "bg-gray-800 border border-gray-600 p-2 rounded my-2 text-center shadow-md";
            div.innerHTML = `<p class="text-white font-bold text-xs">🏛️ ${data.username} ha donato ${data.amount}€!</p>`;
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
            showOverlayNotification(data.username, data.amount);
        });

        document.getElementById('chat-form').addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('message-input');
            if(input.value.trim()) {
                socket.emit('send_message', { message: input.value });
                input.value = '';
            }
        });

        function showOverlayNotification(user, amount) {
            const overlay = document.getElementById('tip-overlay');
            const notif = document.createElement('div');
            notif.className = "bg-black/80 p-4 rounded-xl border border-gray-400 tip-animation backdrop-blur-sm text-center shadow-2xl";
            notif.innerHTML = `<h3 class="text-lg font-bold text-white">GRAZIE!</h3><p class="text-sm text-gray-300 mt-1">${user}</p><p class="text-2xl font-bold text-white mt-1">${amount}€</p>`;
            overlay.appendChild(notif);
            setTimeout(() => { notif.style.opacity = '0'; setTimeout(() => notif.remove(), 500); }, 5000);
        }
    </script>
</body>
</html>
