# Seguridad y alcance

No publiques contraseñas, claves privadas, config.json, known_hosts, transcripciones ni capturas de sistemas corporativos en issues. Adjunta errores anonimizados y versiones.

La aplicación requiere aceptación explícita de claves SSH desconocidas. Verifica la huella por un canal confiable. Una clave cambiada no se acepta automáticamente.

El cliente no implementa un servidor HTTP ni un puerto de escucha para su interfaz: usa Qt WebChannel dentro del proceso. Los sockets SSH salientes y los puertos de servicios externos (por ejemplo, Platón) son independientes. La prueba de integración abre únicamente un puerto efímero de loopback mientras corre el test.

Una transcripción manual contiene la salida remota y puede incluir secretos. El almacén de credenciales protege datos en reposo mediante Windows; no protege frente a malware ejecutado con el mismo usuario. No se exportan contraseñas ni referencias a credenciales en la importación nueva.

Los hashes del ZIP detectan corrupción, no sustituyen una firma de distribución independiente: un atacante capaz de sustituir tanto el ZIP como su hash también puede sustituir el manifest. El instalador verifica por separado la firma Authenticode del instalador de Python y hashes fijos de las dependencias.

No hay un certificado de firma de código de MobHector incluido. No se ha realizado una auditoría externa ni un pentest completo. SFTP publica archivos individualmente; una carpeta completa no es una transacción atómica. Ante pérdida total de conexión puede quedar un temporal remoto que deba limpiarse manualmente. Los enlaces simbólicos remotos no se siguen; se omiten, como en la base anterior.
