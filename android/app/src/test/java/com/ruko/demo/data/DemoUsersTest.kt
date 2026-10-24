package com.ruko.demo.data

import com.ruko.demo.DemoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The shipped demo accounts (sim/demo_users.py) must pass the same checks as a typed sign up. */
class DemoUsersTest {

    private val asset: File = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "app/src/main/assets/${DemoUsers.ASSET}") }
        .plus(generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "src/main/assets/${DemoUsers.ASSET}") })
        .first { it.exists() }

    private val users = DemoUsers.parse(asset.readText())

    @Test
    fun meenaComesFirstAndIdsAreUnique() {
        assertEquals(DemoConfig.DEFAULT_USER_ID, users.first().userId)
        assertEquals(users.size, users.map { it.userId }.toSet().size)
        assertTrue("at least one user besides Meena", users.size >= 2)
    }

    @Test
    fun everyDemoUserPassesSignUpChecks() {
        for (u in users) {
            val (y, m, d) = u.dateOfBirth.split("-")
            val dob = Validators.dateOfBirth(d, m, y)
            assertNotNull(u.userId, dob)
            assertTrue(u.userId, Validators.isAdult(dob!!))
            assertTrue(u.userId, Validators.isName(u.fullName))
            assertTrue(u.userId, Validators.isMobile(u.mobile))
            assertTrue(u.userId, Validators.isEmail(u.email))
            assertTrue(u.userId, Validators.isIfsc(u.ifsc))
            assertTrue(u.userId, Validators.isLast4(u.accountLast4))
            assertTrue(u.userId, Validators.isUpiHandle(u.upiId.substringBefore('@')))
            assertTrue(u.userId, u.language in setOf("en", "hi"))
        }
    }
}
